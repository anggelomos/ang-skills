---
name: edit-notion-document
description: Use only when the user explicitly calls it (for example "/edit-notion-document" or "use edit-notion-document on this page"). Edits an existing Notion page with tracked changes: color-coded additions, modifications and deletions, explanatory comments, and replies to the user's comments. Never load it on your own for ordinary Notion edits.
---

# Edit a Notion document with tracked changes

Once the user calls this skill, every edit you make to the page's content follows these rules until the task is done. Page properties (status, dates, tags) can't hold colors or inline comments, so edit them normally.

## Conventions

- **Agent comments start with `🤖 `.** The Notion connector posts comments as the user's account, so this prefix is the only way to tell your comments from theirs. Every comment you write gets it, and a comment without it belongs to the user.
- **Review colors** are the green, yellow and red backgrounds. Use them only for marks. In Notion-flavored Markdown, use `<span color="green_bg">text</span>` for words inside a block and the block tag's color attribute for a whole block (`<p color="green_bg">`, `<li color="green_bg">`), and likewise `yellow_bg` and `red_bg`. Comments anchor on unique text, so make sure the marked text is unique before commenting on it.
- **Markers** are `[ deleted <code> ]` and `[ moved <code> ]`, each with a red background. `<code>` is a fresh random 4-character alphanumeric code (for example `[ deleted k7q2 ]`), so every marker is unique text that a comment can anchor on.
- **Closing a discussion:** the Notion connector can't resolve comments, and on plans below Business it can't edit or delete them either. So close a discussion by posting a new reply in it: `🤖 [closed]`. A discussion whose last comment is `🤖 [closed]` is closed; skip it. Discussions the user resolved don't show in the comments list (`get_comments` without `include_resolved`); treat that list as the source of truth and skip resolved ones even if the page fetch still shows their anchors, and leave those anchors in place. An empty list means every discussion is resolved, not that the call failed.

## 1. Start of the run: act on replies, then clean up

Fetch the page with its discussions, including the ones on child blocks. A discussion that spans several blocks shows up once per block, so group by discussion ID and treat each thread once.

1. **Act on the user's replies to your old comments first.** For example, if they answered "put it back" on a `🤖 Deleted content` comment, restore that content (marked green) and reply in the thread.
2. **Close finished discussions** (see Conventions). These are:
   - your own discussions that the user never replied to, where every comment starts with `🤖`;
   - the user's discussions where your reply is the last comment and the work is finished (`🤖 Done`, or an answer to their question). Leave open a discussion where your last reply asked the user something.

   Never edit or delete the user's comments.
3. **Accept the previous run's marks:**
   - remove the green, yellow and red backgrounds, keeping the text;
   - remove leftover `[ deleted <code> ]` and `[ moved <code> ]` markers. Removing a marker also removes its `Deleted content` or `Moved to` comment, which is expected: the change is accepted.

   Leave every other background color alone, because the user set those on purpose.

## 2. Marking your edits

When you rewrite text that carries the user's comment (a `discussion-urls` attribute on a span), keep that attribute on the new text, or their thread comes off the page. What anchors a user's discussion is the `discussion-urls` span on the text, not the block (Notion rebuilds blocks when they move). Before you delete text that carries one of the user's open discussions, move that span onto nearby text that stays; if that isn't possible, keep the text and ask in the thread. When you move text, keep its spans so the threads follow it. A comment on a whole block (a table, for example) has no span, so edit such blocks in place and never replace the whole block.

Mark the smallest unit that changed: a phrase inline when the change is inside a block, and the whole block when the block itself is new.

- **Added:** green background on the new content. A new table gets `color="green_bg"` on every row (`<tr>`), because tables have no color of their own. New rows or columns in an existing table get `color="green_bg"` on each new cell (`<td>`).
- **Modified:** yellow background on the new version, plus a comment anchored on it: `🤖 Original content: "<original content>"`.
  - A rewrite of the same content is one modification (rewording a phrase to drop a reference counts too), never a red deletion beside a green addition. Use red plus green only for a removal and an addition that are unrelated.
  - For a formatting-only change (bold, a link, a heading level, a paragraph turned into a list), the comment says exactly what the old form was, for example `🤖 Original content: "H3 heading"` or `🤖 Original content: "two separate paragraphs, no list"`.
  - When a modification spans several blocks, mark every block yellow and put an `Original content` comment on each one, holding that block's original.
- **Deleted:** put `[ deleted <code> ]` with a red background where the content was, plus a comment anchored on the marker: `🤖 Deleted content: "<deleted content>"`.
  - When a whole block goes, leave a block of the same kind containing only the marker: a bullet inside a list, so the list doesn't split, and a paragraph elsewhere.
  - Several adjacent blocks deleted together get one marker, and its comment holds all of the removed content, one block per line (list items keep their `- `).
- **Moved:** put `[ moved <code> ]` with a red background at the old spot, plus the comment `🤖 Moved to: "<the moved section's heading, or the first words of the moved content>"`. Mark every moved block green at its new spot, as an addition, and comment on its first block: `🤖 Moved from: "[ moved <code> ]"`, with the same code as the marker, so the user can find where it came from.
- **Blocks the user colored themselves:** never change a block's existing non-review background. Mark only the text inside it, inline.
- **Long content in a comment:** comments hold about 2,000 characters. Keep as much of the original or deleted content as fits (about 1,900 characters), then end with `… (+N characters)`.

## 3. The user's comments

Handle each user discussion where the user's comment comes after your last reply (or you haven't replied yet). Skip closed ones and ones where your reply is still the last comment:

- **A request**, including one worded as a question ("Turn this into a bullet point?"): make the change, marked by the rules above, then reply in the same thread with `🤖 Done`.
- **A question:** answer it in the same thread.
- **Unclear:** ask in the same thread instead of guessing.

Every reply is a single short, plain sentence. You can't resolve the user's comments; they resolve them after reading your reply.

## 4. End of the run

Post a one-line summary in the chat where you were called, for example "3 added, 2 changed, 1 deleted, 1 moved, 4 comments answered." Don't add a page comment for it.
