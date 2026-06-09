---
id:                 # YYYYMMDD-<theme>-<slug>, shared with Ready_for_upload/<id>/
theme:              # horror | goon | goonhorror
source:             # reddit | llm | hybrid
source_url:         # original Reddit permalink if source=reddit/hybrid, else blank
background_category: # folder name under background_videos/ (e.g. minecraft_bhop)
voice:              # TTS voice id (e.g. edge-tts en-US-GuyNeural)
status:             # draft | voiced | rendered | uploaded
created:            # YYYY-MM-DD
description:        # upload description, precomputed with the story for source=llm (else blank)
tags:               # comma-separated upload tags, precomputed for source=llm (else blank)
quality:            # critic's harsh 0-10 score of the script (0 = never judged)
quality_notes:      # critic's one-line notes on what was weak / what it changed
series_id:          # blank for standalone; shared id for all parts of a series
part:               # 0 for standalone, else 1..N
total_parts:        # 1 for standalone, else N
---

# Title Goes Here

The full body below is the EXACT text read aloud by the TTS voice and is the source the
word-synced subtitles are generated from. Write clean spoken prose only:

- No markdown formatting, links, or emoji inside the story body.
- No stage directions or notes in the prose (put those in frontmatter/comments).
- Spell out anything that should be voiced; expand abbreviations and numbers as you want
  them spoken.

Replace this paragraph with the story.
