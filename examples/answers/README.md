# Worked answers — for the wrap, not the class

One script per quest family (`docs/QUESTS.md`) plus `bot_chokepoint.py`,
the tower-placement answer (SESSION_PLAN §6). They are deliberately not in
the template menu or the bot allowlist: hand them out at the wrap, after the
room has had its go. To fly one on a dev server as a bot, start the server
with `EXTRA_BOT_SCRIPTS=answers/quest_route,answers/quest_predict,answers/quest_compute`
and spawn it from `/admin` by that name (`make bots SCRIPT=answers/quest_route`
works too). Headless: `cd server && uv run python -m tools.balance
--extra-bot-scripts answers/quest_route --bots "4:bot_siege 1:answers/quest_route"`.

Each quest answer enrols itself (`drone.say("quest")`), loops forever like a
bot, and solves every quest of its family it hears; the other families'
lines are ignored, so the three can run side by side. They parse the lines
as the server emits them (`docs/QUESTS.md`): `^(room )?quest (\d+)` ids,
positions as `N <int> E <int>`.
