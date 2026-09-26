# DATLUME project rules

Before changing DATLUME behavior, read `docs/00-document-index.md` and the relevant requirement/design document.
Treat source code and generated data as the implementation truth, and `docs/` as the design intent.
When a change affects requirements, architecture, data semantics, operations, QA, security, or monetization, update the matching document in the same change.
Never guess or fabricate missing public-data values. Keep secrets out of Git, logs, `public/`, and `dist/`.
For significant changes, run the applicable data audit, build, HTML audit, PC/mobile E2E, and production verification described in `docs/06-test-quality.md`.

## Development

When starting the dev server, use background mode:

```
astro dev --background
```

Manage the background server with `astro dev stop`, `astro dev status`, and `astro dev logs`.

## Documentation

Full documentation: https://docs.astro.build

Consult these guides before working on related tasks:

- [Adding pages, dynamic routes, or middleware](https://docs.astro.build/en/guides/routing/)
- [Working with Astro components](https://docs.astro.build/en/basics/astro-components/)
- [Using React, Vue, Svelte, or other framework components](https://docs.astro.build/en/guides/framework-components/)
- [Adding or managing content](https://docs.astro.build/en/guides/content-collections/)
- [Adding styles or using Tailwind](https://docs.astro.build/en/guides/styling/)
- [Supporting multiple languages](https://docs.astro.build/en/guides/internationalization/)
