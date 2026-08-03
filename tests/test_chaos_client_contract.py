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
both sides in the same commit.
"""
import pytest

from services.chaos.events import replay_chain
from services.chaos.seed import seed_for_day

# day -> (seed the client derived, first 25 events it produced)
CLIENT_OUTPUT = {
    "2026-08-03": (
        3632149304,
        "c:walls,c:speed,c:growth,r:mirror,c:speed,e:twins,e:twins,c:speed,"
        "r:mirror,r:mirror,e:dark,c:speed,e:dark,r:portal,l:reverse,r:mirror,"
        "r:double,r:mirror,c:ghost,c:walls,c:ghost,c:growth,e:twins,r:portal,r:mirror"
    ),
    "2026-08-04": (
        4197617581,
        "c:growth,c:speed,c:growth,c:walls,c:invert,r:double,e:dark,r:double,"
        "r:portal,e:golden,r:double,r:mirror,c:ghost,r:portal,c:walls,e:twins,"
        "c:walls,r:mirror,r:double,e:dark,r:mirror,c:ghost,r:portal,r:double,c:ghost"
    ),
    "2026-12-31": (
        4131590803,
        "c:invert,c:ghost,r:double,c:ghost,c:growth,r:double,r:portal,l:reverse,"
        "r:portal,r:double,r:mirror,c:ghost,e:twins,c:speed,e:twins,c:speed,"
        "r:mirror,r:portal,e:dark,r:double,e:dark,e:dark,r:double,r:double,l:reverse"
    ),
    "2027-01-01": (
        3773745198,
        "c:walls,r:mirror,r:double,e:twins,e:golden,r:double,e:dark,e:golden,"
        "c:speed,c:speed,r:mirror,c:walls,l:reverse,r:portal,e:dark,c:ghost,"
        "e:dark,r:double,c:walls,c:walls,e:golden,e:golden,e:twins,c:invert,c:ghost"
    ),
}


@pytest.mark.parametrize("day,expected", CLIENT_OUTPUT.items())
def test_seed_matches_the_client(day, expected):
    assert seed_for_day(day) == expected[0]


@pytest.mark.parametrize("day,expected", CLIENT_OUTPUT.items())
def test_event_chain_matches_the_client(day, expected):
    assert replay_chain(day, 25) == expected[1].split(",")
