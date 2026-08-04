"""The contract between this package and the JavaScript client.

The Mini App generates the day's events on the player's phone; the bot
replays them here to check a submitted run. If the two implementations ever
disagree — a reordered event, a different rarity weight, an extra draw from
the PRNG — every honest result starts getting rejected and the game looks
broken for reasons no one can see.

So the chains below are not computed by Python. They were produced by
running the real client code (webapp/chaos.js) under node:

    node --input-type=module -e 'import {...} from "./chaos.js"; ...'

If a change here is deliberate, regenerate them from the client and update
both sides in the same commit, bumping CATALOGUE_VERSION as well — the
chain changes whenever the event pools do.
"""
import pytest

from services.chaos.events import replay_chain
from services.chaos.seed import seed_for_day

# day -> (seed the client derived, first 25 events it produced)
CLIENT_OUTPUT = {
    "2026-08-03": (
        3632149304,
        "c:invert,c:speed,c:wander,r:shed,c:walls,e:slow,e:slow,c:speed,r:shed,"
        "r:shed,e:dark,c:walls,e:dark,r:portal,l:reverse,r:shed,r:mirror,r:shed,"
        "c:ghost,c:walls,c:growth,c:wander,e:slow,r:portal,r:shed"
    ),
    "2026-08-04": (
        4197617581,
        "c:wander,c:speed,c:wander,c:invert,c:ghost,r:double,e:dark,r:double,"
        "r:portal,e:twins,r:double,r:shed,c:growth,r:double,c:walls,e:slow,c:walls,"
        "r:mirror,r:mirror,e:dark,r:shed,c:ghost,r:portal,r:double,c:ghost"
    ),
    "2026-12-31": (
        4131590803,
        "c:invert,c:growth,r:mirror,c:ghost,c:wander,r:double,r:double,l:swarm,"
        "r:portal,r:double,r:shed,c:growth,e:twins,c:speed,e:slow,c:speed,r:mirror,"
        "r:portal,e:dark,r:double,e:dark,e:dark,r:double,r:mirror,l:swarm"
    ),
    "2027-01-01": (
        3773745198,
        "c:walls,r:shed,r:double,e:slow,e:twins,r:double,e:dark,e:golden,c:speed,"
        "c:speed,r:shed,c:walls,l:swarm,r:portal,e:dark,c:growth,e:dark,r:double,"
        "c:invert,c:walls,e:golden,e:golden,e:twins,c:invert,c:growth"
    ),
}


@pytest.mark.parametrize("day,expected", CLIENT_OUTPUT.items())
def test_seed_matches_the_client(day, expected):
    assert seed_for_day(day) == expected[0]


@pytest.mark.parametrize("day,expected", CLIENT_OUTPUT.items())
def test_event_chain_matches_the_client(day, expected):
    assert replay_chain(day, 25) == expected[1].split(",")
