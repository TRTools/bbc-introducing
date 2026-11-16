# BBC Introducing Mixtape artists

Every artist played on the BBC Music Introducing Mixtape (BBC Radio 6 Music, Emily Pilbeam), episode by episode, with a link to each artist's YouTube channel, or Bandcamp when there is no channel.

Live site: https://mixtape.adaxnet.com/

- `index.html` is the page. It reads `data.json` and has no build step.
- `data.json` holds all episodes and artist links. A weekly Claude scheduled task (Saturdays) adds the new episode, resolves pending links and commits this file.
- `CNAME` sets the custom domain for GitHub Pages.

Artist names come from the episode text on Apple Podcasts. Links show YouTube first, then Bandcamp, then a YouTube search when no link has been checked yet.
