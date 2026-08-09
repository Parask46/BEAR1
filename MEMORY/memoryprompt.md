### Obsidian Markdown Formatting Rules
When writing or formatting notes for long-term memory, you MUST use strict Obsidian syntax and treat every piece of memory as an interconnected node in your knowledge graph:

1. **Always Create Connected Nodes:** It is extremely important to continuously create notes as nodes in your memory graph. Every node must connect to existing concepts using internal `[[Wikilinks]]` so no note exists in isolation.
2. **Frontmatter:** Always start new notes with YAML metadata.
   ---
   tags: [memory, ai-generated]
   ---
3. **Internal Links (Wikilinks):** Use `[[Node Name]]` to connect concepts together in the knowledge graph. Use `[[Node Name|Display Text]]` to change visible text.
4. **Tags:** Use hashtag syntax like `#important` or nested tags like `#project/bear`.
5. **Callouts:** Use blockquotes with bracketed types for emphasis:
   > [!info] Summary
   > This is a key piece of information.
   (Valid types: `[!note]`, `[!info]`, `[!todo]`, `[!warning]`, `[!important]`, `[!success]`)
6. **Highlights:** Use `==highlighted text==` to make key concepts stand out.
7. **Task Lists:** - [ ] Task to do
   - [x] Completed task
8. **Embeds:** Use `![[Node Name]]` if you need to embed the contents of another node.

Be proactive. Whenever you learn a new fact about the user or a topic, create a new node for it immediately and link it back to relevant existing nodes in `MEMORY-LONG`.