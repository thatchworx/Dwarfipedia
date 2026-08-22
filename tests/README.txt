Browser-level tests
===================

These load the REAL index.html, map.js and vectorborders.js into a real DOM
(jsdom) and drive the actual router against a running server. They exist
because a whole class of bug in this app is invisible to API testing:

  - map.js threw at load time because it bound a listener to an element that
    only exists after you navigate to the map. window.MapView was therefore
    never defined and the entire map silently did nothing. Every API endpoint
    it depends on returned 200 the whole time.
  - /api/w/<world>/meta didn't include width/height, so the renderer computed
    NaN draw dimensions and painted nothing. No error was raised anywhere.

Neither shows up in curl. Both show up here in seconds.

Run:
    cd server && python3 server.py &        # needs a world imported
    npm install jsdom
    node tests/test_map_route.mjs
    node tests/test_entity_page.mjs

Expect "ERRORS: none" plus non-zero counts (sites, lore sections, etc).
A zero count means the view rendered but stayed empty, which is a real bug
even when nothing threw.
