# voice-profile-mcp

The hosted measurement service behind the [voice-profile](https://github.com/genideva/voice-profile) plugin, for ChatGPT. It's a small, stateless [MCP](https://modelcontextprotocol.io) server. The chat model leads the conversation, and this server does the counting, so the numbers are exact rather than estimated.

**Live endpoint:** `https://voice-profile-mcp.vercel.app/mcp` (streamable HTTP, no authentication).

**It stores nothing.** Every request is measured in memory and the result is returned. No database, no files, no request logging.

## Tools

| Tool | What it does |
|---|---|
| `analyze_writing` | Measures ten surface features of each writing sample (sentence length and variation, short and long sentence shares, contractions, first and second person, questions, paragraph length). With 8+ unlabeled samples it also suggests whether the writer has two distinct modes. |
| `build_voice_profile` | Turns labeled samples into a profile: a working range per feature, per writing mode, plus a cross-check of how distinct the modes are. Returns the profile for the user to save. |
| `check_draft` | Scores a draft against one mode of a saved profile. Pass or fail per feature, which way to move, and any banned words. |
| `compare_to_authors` | Compares a sample, or a profile, with 37 public-domain authors, fiction and non-fiction, on measured style, and returns the closest authors and the closest author per feature. |

All four tools are read-only (`readOnlyHint: true`, `destructiveHint: false`, `openWorldHint: false`).

**Rules the server enforces:**
- A sample is measured only if `ai_touched` is `"no"`. AI-assisted text measures the assistant's version of the writer.
- Written prose only. Call transcripts stay with the client-side plugin, which removes other speakers before anything is measured.
- Limits: 60 samples and 120,000 words per request, 15,000 words per draft, a 1.5 MB body, and 60 requests per minute per client.

## The author library

`api/_core/authors.json` holds measured numbers, and no text, for 37 public-domain works from Project Gutenberg.

- **Fiction:** Austen, Dickens, Wilde, Melville, Shelley, Conan Doyle, Poe and Swift.
- **Essays and lectures:** Emerson, Wollstonecraft, Paine, Chesterton, Du Bois and William James.
- **Memoir:** Twain, Thoreau, Douglass, Franklin, Booker T. Washington, Helen Keller and Jane Addams.
- **Advice and business:** Arnold Bennett, Samuel Smiles, Emily Post, Frederick Winslow Taylor, Henry Ford and Andrew Carnegie.
- **Technology:** Charles Babbage, and Dyer and Martin's biography of Edison.
- **Finance:** Edwin Lefevre, Walter Bagehot and Charles Mackay.
- **Medical:** Florence Nightingale and Oliver Wendell Holmes Sr.
- **Biography:** Lytton Strachey, James Boswell and Ida M. Tarbell.

Every group after fiction is non-fiction, so a blog post, memo or advice piece has prose in its own register to sit near, not just novels. Each book is cut into chunks of about 1,500 words and measured with the same code as everything else.

Rebuild it with `python3 tools/build_authors.py <cache-dir>`.

The comparison leaves out contractions, because older printing used elisions ("receiv'd", "'tis") that distort the count. It compares style only. It makes no claims about personality, quality, or the authors as people.

## Same numbers as the plugin

`api/_core/textstats.py`, `build_profile.py` and `verify.py` are byte-for-byte copies of the plugin's scripts. `tests/test_server.py` checks that the copies are identical, and that a profile built through the server matches one built with the plugin's command-line tools. When the plugin's scripts change, copy them over and run the tests.

## Run it

```bash
python3 server.py            # http://localhost:8787/mcp
python3 -m unittest discover tests
```

There are no dependencies: standard-library Python only.

**Try it from any MCP client:**

```bash
npx @modelcontextprotocol/inspector --cli https://voice-profile-mcp.vercel.app/mcp --transport http --method tools/list
```

In ChatGPT, it comes bundled with the Voice Profile plugin, so there's nothing to connect by hand.

**Deploying (Vercel):** `api/mcp.py` is the function and `vercel.json` routes `/mcp` and `/.well-known/openai-apps-challenge` to it. To pass OpenAI's domain verification, set the environment variable `OPENAI_APPS_CHALLENGE` to the token from the plugin dashboard.

## Privacy and terms

See [PRIVACY.md](PRIVACY.md) and the plugin's [TERMS.md](https://github.com/genideva/voice-profile/blob/main/TERMS.md).

## License

MIT
