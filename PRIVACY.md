# Privacy policy: voice-profile measurement service

**Effective:** on first deployment · **Applies to:** the hosted MCP server that ChatGPT calls for the Voice Profile plugin.

## What the service receives

When you use Voice Profile in ChatGPT, ChatGPT sends this service only what a tool needs:

- the writing samples you choose to measure, each with a title and your answer to "did AI help write this?";
- a draft to check, and the profile you saved earlier;
- for author comparison, one sample or one profile.

It never receives your chat history, account details or location.

## What it does with it

It counts surface features of the text (sentence lengths, contractions, pronouns, questions, paragraph lengths), compares them with ranges, and sends the numbers back. That is the only purpose.

## Retention

- **Your writing is not stored.** It is processed in memory and discarded when the response is sent. There is no database and nothing is written to disk.
- **Request bodies are not logged.** The server writes no logs about requests.
- **The hosting provider** records standard metadata for each request (time, size, status code, and network address) to operate and protect the service. These logs never contain your text, and the provider keeps them for its standard retention period.
- **Rate limiting** keeps a short-lived, in-memory count per network address for one minute. It is never written anywhere.

## Who sees it

No one. No person reads submitted text. It is not shared, sold, or used to train any model. The service makes no outbound calls.

## Your controls

- Choose what to send. Only samples you mark as written without AI are measured.
- Your profile lives with you. The service keeps no copy, so deleting your saved file deletes your profile.
- For full local processing, use the open-source plugin in Claude Code or Codex, where the same measurements run on your own machine.

## Children

Not intended for users under 18.

## Contact

Open an issue at [github.com/genideva/voice-profile/issues](https://github.com/genideva/voice-profile/issues). This policy's history is public in this repository.
