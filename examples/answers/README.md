# Worked answers — for the wrap, not the class

One script per quest family (`docs/QUESTS.md`). They are deliberately not in
the template menu or the bot allowlist: hand them out at the wrap, after the
room has had its go. To fly one on a dev server as a bot, start the server
with `EXTRA_BOT_SCRIPTS=answers/quest_route,answers/quest_predict,answers/quest_compute`
and spawn it from `/admin` by that name.

Each one enrols itself (`drone.say("quest")`), loops forever like a bot, and
solves every quest of its family it hears; the other families' lines are
ignored, so the three can run side by side.
