"""
Source B: Curated Indian D2C brand lists.

Hand-compiled from brand roundups (Inc42, YourStory, Entrackr) and known
Indian D2C Shopify storefronts.  No marketplaces, aggregators, or delivery apps.
"""

from __future__ import annotations

from utils import normalize_domain

_RAW_DOMAINS: list[str] = [
    # Fashion & Apparel
    "bewakoof.com", "bombayshirtcompany.com", "snitch.co.in",
    "thesouledstore.com", "fablestreet.com", "andamen.com",
    "urbanmonkey.com", "tfrstore.com", "nobero.com", "powerlook.in",
    "damensch.com", "virfrancisco.in", "brantaclothing.com",
    "rare-rabbit.com", "truebrowns.com", "nushclothing.com",
    "houseofmodello.com", "kottylifestyle.com", "muftimenswear.com",
    "here-now.in", "tigc.in", "libas.in",
    # Beauty & Personal Care
    "mamaearth.in", "sugarcosmetics.com", "plumgoodness.com",
    "mcaffeine.com", "wowskinscience.com", "juicychemistry.com",
    "kama-ayurveda.com", "fixderma.com", "minimalist.co.in",
    "arata.in", "themancompany.com", "beardo.in",
    "dotandkey.com", "pilgrimsindia.com", "foxtale.in",
    "bellavitaorganic.com", "thedermaco.com", "plix.in",
    "re-equil.com", "clinikally.com", "nua.in",
    "ras-beauty.com", "bombayshavingcompany.com", "ustraa.com",
    "manmatters.com", "perfora.in", "beminimalist.co",
    "dermaessentia.com", "fix-my-curls.com", "skinnsi.com",
    # Food & Beverage
    "yogabar.com", "happilo.com", "true-elements.com",
    "slurrpfarm.com", "oziva.in", "vahdam.in",
    "sleepyowl.co", "licious.in", "auric.com",
    "cosmicdealer.com", "thewholetruthfoods.com", "snackible.com",
    "epigamia.com", "rawpressery.com", "paperboatdrinks.com",
    # Health & Wellness
    "wellbeing-nutrition.com", "kapiva.com", "traya.health",
    "vedistry.com", "nirvasa.com", "boldfit.in",
    "cosmix.in", "gritzo.com", "muscleblaze.com",
    "nutrabay.com", "cureveda.com", "truebasics.com",
    # Home & Living
    "wakefit.co", "thesleepcompany.in", "woodenstreet.com",
    "nestasia.in", "ellementry.com", "thecottoncompany.com",
    "studioochre.com", "bepurehome.com", "sleepycat.in",
    # Electronics & Audio
    "boat-lifestyle.com", "noise.com", "crossbeats.com",
    "fireboltt.com", "ptron.in", "portronics.com",
    "truke.in", "mivi.in", "boult-audio.com", "atomberg.com",
    # Jewellery & Accessories
    "caratlane.com", "bluestone.com", "melorra.com",
    "candere.com", "giva.co", "tribebyamrapali.com",
    "rubans.in", "tistabene.com", "yellowchimes.com",
    # Baby & Kids
    "hopscotch.in", "superbottoms.com", "thelittleboo.com",
    # Pet
    "headsupfortails.com", "supertails.com", "wiggles.in",
    # Bags, Footwear & Accessories
    "mokobara.com", "neemans.com", "flatheads.in",
    "paaduks.com", "monkstory.in", "lavie-sport.com",
    "baggit.com", "thelabellife.com",
    # Indian Ethnic / Fashion
    "global-desi.in", "aurelia-india.com", "soch.in",
    "w-india.com", "rangriti.com", "kalki.fashion",
    "karagiri.com", "jaypore.com", "tjori.com",
    "suta.in", "bunaai.com", "aachho.com",
    "okhai.org", "rangsutra.com", "itokri.com",
    "priyaasi.com", "janasya.com", "vastramay.com",
    "mulmulclothing.com",
    # Premium / Niche
    "stalkbuylove.com", "faballey.com", "sassafras.in",
    "oxolloxo.com", "streetstylestalk.com",
    # Handicrafts / Artisan
    "chumbak.com", "indiahaat.com", "artisansofkashmir.com",
    "desiweaves.com", "thepostbox.in", "dailyobjects.com",
    # Other confirmed Indian Shopify storefronts
    "nicobar.com", "ugaoo.com", "soulflower.biz",
    "earthrhythm.com", "justaherbs.in", "soultree.in",
    "blissclub.com", "bummer.in", "theindiangarage.com",
    "wildcraft.com", "headphonezone.in",
    # Confirmed from spike results
    "nivaaya.in", "vaku.in", "aurimo.in", "goldenglitter.in",
    "uniqkart.in", "monri.in", "theformalclub.in", "drveda.in",
    "jewelpanda.in", "freedomtree.in", "cordstudio.in",
    "yogabars.in", "mumkins.in", "brustro.in", "stanwellskids.in",
    "foxin.in", "eyejack.in", "rdoverseas.in", "dawntown.co.in",
    "uniqbuy.in", "303diecastshop.in", "printmine.in",
    "niharikafashion.in",
    # Additional curated
    "discoverpilgrim.com", "skinroots.in",
    "myborosil.com", "pebblecart.com",
    "hkvivits.com", "healthkart.com",
    "spacely.in", "housetry.com",
    "countrydelight.in", "freshtohome.com",
    "snacc.com", "nuts.com",
    "zoomin.com", "printo.in",
    "fancode.com",
]


def get_candidates() -> list[dict]:
    """
    Return curated D2C domains as candidate dicts:
        {"domain": <canonical>, "source": "d2c_curated", "raw": <original>}

    Deduped by canonical registrable domain.
    """
    seen: set[str] = set()
    results: list[dict] = []

    for raw in _RAW_DOMAINS:
        # myshopify domains kept verbatim as canonical
        if "myshopify.com" in raw:
            key = raw.lower().strip()
            if key not in seen:
                seen.add(key)
                results.append({"domain": key, "source": "d2c_curated", "raw": raw})
            continue

        canonical = normalize_domain(raw)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        results.append({"domain": canonical, "source": "d2c_curated", "raw": raw})

    print(f"[d2c] {len(results)} unique curated D2C candidates")
    return results


if __name__ == "__main__":
    candidates = get_candidates()
    print(f"Total: {len(candidates)}")
