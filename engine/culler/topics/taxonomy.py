"""The topic categories for each kind of shoot.

Each category has a few plain-English descriptions. The vision model (CLIP) compares a
photo with those descriptions and picks the closest. ``faces`` is how many faces a photo
in that category normally shows, as (fewest, most); it nudges the choice, since face
counting is more dependable than CLIP at telling one person from two from a group.

To add a kind of shoot or a category, edit this file. Nothing else needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass

ANY = (0, 999)


@dataclass(frozen=True)
class Category:
    name: str
    prompts: tuple[str, ...]
    faces: tuple[int, int] = ANY


def _c(name: str, faces: tuple[int, int], *prompts: str) -> Category:
    return Category(name, prompts, faces)


SHOOT_TYPES: dict[str, tuple[str, tuple[Category, ...]]] = {
    "general": ("General", (
        _c("Group photos", (3, 999), "a group photo of several people", "a posed photo of a group of people"),
        _c("Pairs and couples", (2, 2), "a photo of two people together", "a portrait of a couple"),
        _c("Single portraits", (1, 1), "a portrait of one person", "a close-up photo of a person"),
        _c("Candids and action", (1, 999), "a candid photo of people doing something", "people in the middle of an activity"),
        _c("Details and objects", (0, 0), "a close-up photo of an object", "a detail shot of a small object"),
        _c("Places and scenery", (0, 1), "a photo of a landscape or a building", "a wide photo of a place with no people"),
    )),
    "wedding": ("Wedding", (
        _c("Group photos", (3, 999), "a posed group photo of wedding guests", "a formal family group photo at a wedding", "the wedding party posing together"),
        _c("Couple portraits", (2, 2), "a portrait of a bride and groom together", "a romantic portrait of a newly married couple"),
        _c("Single portraits", (1, 1), "a portrait of a bride alone", "a portrait of a groom alone", "a portrait of one wedding guest"),
        _c("Ceremony", ANY, "a wedding ceremony with the couple at the altar", "a couple exchanging vows or rings in front of guests", "a bride walking down the aisle"),
        _c("Reception and dancing", (1, 999), "people dancing at a wedding reception", "a toast or speech at a wedding reception", "guests eating at a wedding dinner"),
        _c("Getting ready", (1, 6), "a bride getting ready, having her hair and makeup done", "a groom getting dressed before the wedding"),
        _c("Details", (0, 0), "a close-up of wedding rings", "a wedding bouquet or flowers", "a wedding cake", "wedding table decorations and place settings", "wedding shoes, dress or invitation laid out"),
        _c("Venue and scenery", (0, 1), "an empty wedding venue", "the outside of a church or wedding venue", "a landscape view with no people"),
    )),
    "portrait": ("Portrait session", (
        _c("Headshots", (1, 1), "a close-up headshot of a person's face and shoulders"),
        _c("Half-length portraits", (1, 1), "a portrait of a person from the waist up"),
        _c("Full-length portraits", (1, 1), "a full-length portrait of a person standing"),
        _c("Couples", (2, 2), "a portrait of two people together"),
        _c("Groups and families", (3, 999), "a family portrait", "a group portrait of several people"),
        _c("Details", (0, 0), "a close-up of hands, clothing or jewellery", "a detail shot of an object"),
    )),
    "event": ("Event", (
        _c("Group photos", (3, 999), "a posed group photo of people at an event"),
        _c("Speakers and stage", (1, 6), "a person speaking on a stage or at a podium", "a panel of speakers in front of an audience", "a performer on stage"),
        _c("Audience and crowd", (3, 999), "an audience watching a presentation", "a crowd of people at an event"),
        _c("Candids", (1, 999), "people talking and laughing at an event", "a candid photo of guests mingling"),
        _c("Portraits", (1, 2), "a portrait of one person at an event", "two people posing for the camera at an event"),
        _c("Venue and decor", (0, 1), "an empty event space with tables and decorations", "a banner, sign or stage with no people"),
        _c("Food and drink", (0, 1), "food on a table at an event", "drinks on a bar"),
    )),
    "travel": ("Travel", (
        _c("Landmarks and architecture", (0, 2), "a famous landmark or monument", "an interesting building or piece of architecture", "the inside of a cathedral, temple or museum"),
        _c("Landscapes and nature", (0, 1), "a landscape with mountains, sea or countryside", "a beach or coastline", "a forest, lake or sunset"),
        _c("Street and city life", ANY, "a busy city street", "a market with stalls and people", "a street scene in a foreign city"),
        _c("People and portraits", (1, 2), "a portrait of a traveller in front of a view", "a portrait of a local person"),
        _c("Group photos", (3, 999), "a group of friends or family posing on holiday"),
        _c("Food and drink", (0, 1), "a plate of food at a restaurant", "a drink on a table", "street food"),
        _c("Details", (0, 0), "a close-up of a small object, sign or texture"),
        _c("Transport", (0, 2), "an airplane, train, boat or car", "an airport or train station"),
    )),
}

# Used when no vision model is installed: categories from the number and size of faces alone.
PEOPLE_BUCKETS = ("Large groups", "Small groups", "Pairs and couples", "Single portraits", "One person, wide", "No people")


def shoot_type_list() -> list[dict]:
    return [{"id": key, "name": name} for key, (name, _) in SHOOT_TYPES.items()]
