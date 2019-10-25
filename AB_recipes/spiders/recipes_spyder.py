from typing import Optional

import scrapy

SORT_BY = "recentlyaired"


class RecipesSpider(scrapy.Spider):
    name = "recipes"
    allowed_domains = ["cookingchanneltv.com", "foodnetwork.com"]
    start_urls = [
        f"https://www.foodnetwork.com/shows/good-eats/recipes/{SORT_BY}-/p/1",
        f"https://www.cookingchanneltv.com/profiles/talent/alton-brown/recipes/{SORT_BY}-/p/1",
        f"https://www.cookingchanneltv.com/shows/good-eats/recipes/{SORT_BY}-/p/1",
        f"https://www.cookingchanneltv.com/shows/good-eats-reloaded/recipes/{SORT_BY}-/p/1",
    ]

    def parse(self, response: scrapy.http.TextResponse):
        self.logger.info("Parse function called on %s", response.url)

        # set a list of seen URLs, to skip.
        seen_urls = set()
        if getattr(self, "skip", None) == "existing":
            # skip URLs already saved
            raise NotImplementedError()

        # iterate over each row in the page
        for recipe_row in response.css(".listRecipe .m-MediaBlock"):
            recipe_url = response.urljoin(
                recipe_row.css(".m-MediaBlock__m-TextWrap").xpath(".//@href").get()
            )
            if recipe_url not in seen_urls:
                seen_urls.add(recipe_url)
                yield self.parse_summary(response, recipe_row, recipe_url)
            else:
                # TODO: add the new response.url to the existing item
                pass

        # continue to crawl next page
        if getattr(self, "follow", None) == "next":
            for next_page_a in response.css(".o-Pagination__a-NextButton"):
                target_url = response.urljoin(next_page_a.attrib["href"])
                if SORT_BY not in target_url:
                    self.logger.error(
                        "following 'next' from url %s leads to %s",
                        response.url,
                        target_url,
                    )
                yield response.follow(next_page_a, callback=self.parse)

    def parse_summary(
        self,
        response: scrapy.http.TextResponse,
        recipe_row: scrapy.Selector,
        recipe_url: str,
    ):
        def url_parse(url: Optional[str]):
            if url is None:
                return url
            return response.urljoin(url)

        # get recipe metadata
        data = dict(id=None, credit=None, name=None)
        data["url_recipe"] = recipe_url
        data["url_list"] = response.url
        data["url_image"] = url_parse(recipe_row.xpath(".//img/@src").get())
        data["image_urls"] = [
            response.urljoin(url) for url in recipe_row.xpath(".//img/@src").getall()
        ]
        if data["url_recipe"] is not None:
            url_id = data["url_recipe"].split("-")[-1]
            try:
                data["id"] = int(url_id)
            except ValueError:
                # some recipes don't have an id in the url
                data["id"] = -2  # bad-url
        else:
            data["id"] = -1  # no-url
        data["name"] = recipe_row.css(".m-MediaBlock__a-HeadlineText::text").get()
        data["credit"] = recipe_row.css(".m-MediaBlock__a-Credit--Text::text").get()

        # get the recipe itself
        # TODO: in scrapy 1.7, use cb_kwargs={"data": data}
        request = scrapy.Request(
            data["url_recipe"], callback=self.parse_recipe, meta={"data": data}
        )
        return request

    # TODO: in scrapy 1.7, parse_recipe(response, data)
    @staticmethod
    def parse_recipe(response: scrapy.http.TextResponse):
        data = response.meta["data"]

        # lead: get image
        recipe_lead = response.xpath(".//div[@data-module='recipe-lead']")[0]
        image_urls = [
            response.urljoin(url) for url in recipe_lead.xpath(".//img//@src").getall()
        ]
        data["image_urls"] += [url for url in image_urls if url not in data["image_urls"]]

        # summary: get level / time / yield
        recipe_summary = response.xpath(".//div[@data-module='recipe-summary']")[0]
        for li in recipe_summary.css(".o-RecipeInfo").xpath(".//li"):
            headline, *desc = li.xpath(".//span/text()").getall()
            headline = headline.strip().strip(":").lower()
            desc = "; ".join(desc).strip()
            data[headline] = desc

        # footer: get src / categories
        recipe_footer = response.css(".recipe-body-footer")[0]
        recipe_src = recipe_footer.css(".o-VideoPromo .m-MediaBlock__m-TextWrap")
        if recipe_src:
            for src in recipe_src[0].css(".m-MediaBlock__a-Source"):
                prefix = src.css(".m-MediaBlock__a-Source--Prefix::text").get()
                prefix = prefix.strip().strip(":").lower()
                name = src.css(".m-MediaBlock__a-Source--Name a::text").getall()
                data[f"src_{prefix}"] = name
        data["categories"] = recipe_footer.css(".o-Tags").xpath(".//a/text()").getall()

        # body: get Ingredients / Method / Cook’s Note
        recipe_body = response.css(".recipe-body")[0]
        equipment = recipe_body.css(".o-SpecialEquipment::text").getall()
        data["equipment"] = "".join(equipment).strip()
        chef_notes = recipe_body.css(".o-ChefNotes__a-Description ::text").getall()
        data["chef_notes"] = "".join(chef_notes).strip()
        ingredients = recipe_body.css(".o-Ingredients__m-Body")[0]
        data["ingredients"] = [
            s.strip() for s in ingredients.xpath(".//*/text()").getall()
        ]
        recipe_method = response.xpath(
            ".//section[@data-module='recipe-method']"
        ).xpath(".//*/text()")
        data["method"] = [s.strip() for s in recipe_method.getall() if s.strip()]

        yield data
