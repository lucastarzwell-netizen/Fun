from house_agent.addresses import address_key
from house_agent.agent.sources import redfin_county_url, redfin_filter
from house_agent.schemas import Criteria, Region


def test_address_key_matches_common_variants():
    a = address_key("17902 State Route 2", "Wauseon", "OH")
    b = address_key("17902 State Rte. 2", "wauseon", "oh")
    assert a == b
    assert address_key("825 East River Road", "Flushing", "MI") == address_key(
        "825 E River Rd", "Flushing", "MI"
    )
    assert address_key("3300 Mackin Rd Unit G", "Flint", "MI") == address_key(
        "3300 Mackin Rd #G", "Flint", "MI"
    )


def test_address_key_distinguishes_cities():
    assert address_key("1 Main St", "Adrian", "MI") != address_key("1 Main St", "Monroe", "MI")


def test_redfin_county_url_matches_routine_pattern():
    c = Criteria(min_price=100_000, max_price=175_000, min_acres=1)
    region = Region(name="Lenawee County", state="MI", anchor="DTW", redfin_county_id=1393)
    assert redfin_county_url(region, c) == (
        "https://www.redfin.com/county/1393/MI/Lenawee-County/filter/"
        "property-type=house,min-price=100k,max-price=175k,min-lot-size=1-acre"
    )


def test_redfin_filter_rounds_lot_down_and_handles_odd_prices():
    c = Criteria(min_price=162_500, max_price=None, min_acres=1.5, min_beds=3)
    assert redfin_filter(c) == "property-type=house,min-price=162.5k,min-beds=3,min-lot-size=1-acre"


def test_region_without_id_has_no_url():
    region = Region(name="St. Clair County", state="MI", anchor="DTW")
    assert redfin_county_url(region, Criteria()) is None


def test_criteria_block_switches_between_home_and_land_rules():
    from house_agent.agent.prompts import criteria_block

    land = {
        "uses": ["Build a home", "Hunting"],
        "must_have": ["Year-round road access"],
        "nice_to_have": ["Pond or creek"],
        "zoning": [],
        "avoid": ["Mostly wetlands"],
    }
    land_only = criteria_block(Criteria(property_types=["land"], land=land))
    assert "Condition rules for homes" not in land_only
    assert "Must have (reject land without these): Year-round road access" in land_only
    assert "Acceptable zoning: any" in land_only

    both = criteria_block(Criteria(property_types=["house", "land"], land=land))
    assert "Condition rules for homes" in both and "Vacant land preferences" in both

    homes = criteria_block(Criteria(property_types=["house"], land=land))
    assert "Vacant land preferences" not in homes


def test_bed_bath_filters_never_hide_land():
    from house_agent.agent.prompts import criteria_block

    region = Region(name="Orange County", state="VA", anchor="X", redfin_county_id=1)
    mixed = Criteria(property_types=["house", "land"], min_beds=3, min_baths=2)
    assert "min-beds" not in redfin_county_url(region, mixed)
    assert "Beds: at least 3 (homes only" in criteria_block(mixed)

    # Old wizard versions could save a bedroom minimum on a land-only search.
    land = Criteria(property_types=["land"], min_beds=3)
    assert "min-beds" not in redfin_county_url(region, land)
    assert "Beds" not in criteria_block(land)

    homes = Criteria(property_types=["house"], min_beds=3)
    assert "min-beds=3" in redfin_county_url(region, homes)


def test_prompt_includes_feedback_and_previous_rejections():
    from house_agent.agent.prompts import search_prompt

    c = Criteria(feedback=['1 A Rd: you rejected it; the buyer included it anyway: "ok"'])
    text = search_prompt(c, "X County, MI", "DTW", [], [], [], ["2 B Rd, X, MI (was $100,000)"])
    assert "The buyer's corrections to your earlier rejections" in text
    assert "skip them unless the price shown now is lower" in text
    assert "reject_reason" in text
    # Feedback is runtime-only; it never gets saved with the profile.
    assert "feedback" not in c.model_dump()


def test_site_plan_urls_and_land_only_sites():
    from house_agent.agent.sources import site_plan

    region = Region(name="St. Clair County", state="MI", anchor="DTW", redfin_county_id=1421)
    land = Criteria(property_types=["land"], min_acres=1)
    plan = dict(site_plan(land, region, 0))
    assert plan["redfin"].startswith("https://www.redfin.com/county/1421/MI/St-Clair-County/")
    assert plan["zillow"] == "https://www.zillow.com/st-clair-county-mi/"
    assert plan["realtor"].endswith("/realestateandhomes-search/St-Clair-County_MI")
    assert plan["landwatch"] == "https://www.landwatch.com/michigan-land-for-sale/st-clair-county"
    assert "landwatch" not in dict(site_plan(Criteria(), region, 0))  # land only
    assert [k for k, _ in site_plan(Criteria(sites=["zillow"]), region, 3)] == ["zillow"]


def test_search_prompt_lists_sites_in_order():
    from house_agent.agent.prompts import search_prompt

    plan = [("zillow", "https://z"), ("redfin", None)]
    text = search_prompt(Criteria(), "X County, MI", "DTW", plan, [], [])
    assert text.index("- zillow (Zillow). Start here: https://z") < text.index("- redfin (Redfin).")


def test_site_plan_prefers_sites_not_used_last_time():
    from house_agent.agent.sources import site_plan

    region = Region(name="Lenawee County", state="MI", anchor="DTW")
    order = [
        k
        for k, _ in site_plan(
            Criteria(), region, 0, used_last_time={"redfin"}, blocked_last_time={"zillow"}
        )
    ]
    assert order == ["realtor", "homes", "redfin", "zillow"]
