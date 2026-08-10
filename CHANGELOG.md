# Changelog

## [0.1.0](https://github.com/forkwright/typikon/compare/v0.1.0...v0.1.0) (2026-08-10)


### Features

* **_llm:** add T0 corpus per [#667](https://github.com/forkwright/typikon/issues/667) / [#673](https://github.com/forkwright/typikon/issues/673) fleet rollout ([#29](https://github.com/forkwright/typikon/issues/29)) ([3101eba](https://github.com/forkwright/typikon/commit/3101eba3ae4376d9dd276dabcf1d8e48caa8a5dc))
* **agentic:** JSON Schemas, validator, scaffolder, gate orchestrator ([d2ee839](https://github.com/forkwright/typikon/commit/d2ee8396b74a90a2a806535bf5abad86d6d607c5))
* **bin:** typikon-refresh — re-render consumer-side templates after upstream bump ([#30](https://github.com/forkwright/typikon/issues/30)) ([338bb94](https://github.com/forkwright/typikon/commit/338bb94a8eb55051af0095e676173e1db1855f00))
* **ci:** run the release machinery the repo already declared ([#126](https://github.com/forkwright/typikon/issues/126)) ([748d8c3](https://github.com/forkwright/typikon/commit/748d8c3f6b7bad1a8189467c8e1902e0510efadc))
* **ci:** scaffold kanon deploy template ([#17](https://github.com/forkwright/typikon/issues/17)) ([e290a2f](https://github.com/forkwright/typikon/commit/e290a2fef229551acb511371d423eec5d2678743))
* **ci:** wire strict gate harness — csp-enforce, lychee, pa11y, playwright ([3a30a29](https://github.com/forkwright/typikon/commit/3a30a29cca121d7038e3bd4657f5bd0d364d72fb))
* **fonts:** migrate Cormorant Garamond to variable WOFF2 (partial [#2](https://github.com/forkwright/typikon/issues/2)) ([#32](https://github.com/forkwright/typikon/issues/32)) ([f17cc02](https://github.com/forkwright/typikon/commit/f17cc02a745cf82c3d10f42829f40a7032a63fca))
* **fonts:** self-host Cormorant Garamond + Spectral + IBM Plex Mono WOFF2 ([10a7b70](https://github.com/forkwright/typikon/commit/10a7b702f936a998a40f32cef4ab54a41aa0603a))
* **fonts:** ship a display face that actually has Greek ([#125](https://github.com/forkwright/typikon/issues/125)) ([16f9cf1](https://github.com/forkwright/typikon/commit/16f9cf1db27254ef5c01531495a7fab995896d67))
* **headers:** ship Cloudflare Pages strict-CSP + redirects templates ([73e27fe](https://github.com/forkwright/typikon/commit/73e27fe124ff92715464d6ed7682acee13bf78f7))
* **sizing-guide:** emit Schema.org HowTo when decision_tree is present ([#26](https://github.com/forkwright/typikon/issues/26)) ([871669e](https://github.com/forkwright/typikon/commit/871669ea6ab6988eab53a38d804f384136e672dc))
* **stage2:** CI binary pinning + JSON-LD + atom + journal-entry semantics + sitemap exclusion + print ([da950ec](https://github.com/forkwright/typikon/commit/da950ecffaabce80a0491c7ef3e2a20b5e6186c5))
* **stage3:** image pipeline (resize_image + responsive picture) + logo preload ([e406ff9](https://github.com/forkwright/typikon/commit/e406ff9ef385b7a5848a72d6b3f8b8d8e772e52e))
* **stage4:** FAQ + sizing-guide + process-video content types ([561a433](https://github.com/forkwright/typikon/commit/561a43351d35fb2892417cc08db5486e2b4e1370))
* **stage5:** site [#2](https://github.com/forkwright/typikon/issues/2) readiness — fixtures + AGENTIC + SCHEMAS + migration + CI ([21ce092](https://github.com/forkwright/typikon/commit/21ce09253551ea56c73d7b177eeca61719b5d2ee))
* **templates:** enforce required metadata ([#2](https://github.com/forkwright/typikon/issues/2)) ([ae46d94](https://github.com/forkwright/typikon/commit/ae46d945c53bf06815e9b9d8bea7251670ab17b3))
* **theme:** extract ardent design system into reusable Zola templates ([c11ebfc](https://github.com/forkwright/typikon/commit/c11ebfcefc953e20f22ddb351503b6901b300d39))


### Bug Fixes

* **a11y:** darken --text-light from [#78716](https://github.com/forkwright/typikon/issues/78716)C to [#6](https://github.com/forkwright/typikon/issues/6)B6661 (WCAG 2.1 AA) ([bd65afc](https://github.com/forkwright/typikon/commit/bd65afc4efb9cf281dd2a7e1828b8d87b03817ff))
* **a11y:** normalize breadcrumb URLs and keep interactive contrast compliant ([#113](https://github.com/forkwright/typikon/issues/113)) ([504356a](https://github.com/forkwright/typikon/commit/504356ac300f12f16b6fbdf1bc492aace42addf1))
* **audit:** theme-code findings — tokens, motion-pref, dead classes, comment drift ([e24a45c](https://github.com/forkwright/typikon/commit/e24a45cb8da526c2d5ce8d069f13a14acc102afb))
* **check:** assert the gate's own artifacts are ignored, before it writes them ([#118](https://github.com/forkwright/typikon/issues/118)) ([8527a3b](https://github.com/forkwright/typikon/commit/8527a3b301330cfaaf59214d833b4a5700e3a651))
* **ci,schemas:** harden the consumer workflow template and pin triad cardinality ([#42](https://github.com/forkwright/typikon/issues/42)) ([44e6084](https://github.com/forkwright/typikon/commit/44e6084b351de6b2a562f462fe90cacd47c8245d))
* **ci,schemas:** harden the consumer workflow template and pin triad cardinality ([#45](https://github.com/forkwright/typikon/issues/45)) ([f00aad7](https://github.com/forkwright/typikon/commit/f00aad750bb88a84f9f0b1c6350436f2d88495fd))
* **ci+templates:** copy _headers to public/ + mark all hrefs safe ([ea566d5](https://github.com/forkwright/typikon/commit/ea566d57dae403643e8bb0bdc8d30cd17a2cc188))
* **ci:** auto-set CF Pages production_branch on every deploy ([1c45a8b](https://github.com/forkwright/typikon/commit/1c45a8b71210f5a54900e12ad6d19151b9a7b18e))
* **ci:** bound every gate step and pin the fleet gate to a commit ([#104](https://github.com/forkwright/typikon/issues/104)) ([d052896](https://github.com/forkwright/typikon/commit/d052896f712fe465557d95e9f233fafcbb20d0fd))
* **ci:** drive typikon CI to green ([#27](https://github.com/forkwright/typikon/issues/27)) ([73e6d6c](https://github.com/forkwright/typikon/commit/73e6d6ce5feef9a8ae99f986dfaba6e32247dd5b))
* **ci:** drop duplicate exclude_path in lychee.toml ([eef7243](https://github.com/forkwright/typikon/commit/eef724363b2fd1be8b6df25f40346466d4654111))
* **ci:** exclude Buttondown form-action POST + atom.xml self-reference ([0ecb509](https://github.com/forkwright/typikon/commit/0ecb50975beada391218334f94726b0c4869dc95))
* **ci:** exclude instagram.com from lychee external-link checks ([ddf375f](https://github.com/forkwright/typikon/commit/ddf375f4977191aa440ebdf2a90268e3e91dd035))
* **ci:** explicit deploy ref allowlist ([1b225b4](https://github.com/forkwright/typikon/commit/1b225b4cbf8f4a6ffd602c148f27700bd75b0bc6))
* **ci:** give the templates' playwright a config it can load ([#124](https://github.com/forkwright/typikon/issues/124)) ([1aa7e81](https://github.com/forkwright/typikon/commit/1aa7e81f9e78dac4fe84714370a8f504a7dfcbe5))
* **ci:** handle lychee tarball with wrapping dir ([51b5a1a](https://github.com/forkwright/typikon/commit/51b5a1a65f8467fa311aff3842b874a8714437cf))
* **ci:** lychee excludes self-host URLs to break the deploy chicken-and-egg ([#25](https://github.com/forkwright/typikon/issues/25)) ([29962d6](https://github.com/forkwright/typikon/commit/29962d6e04ebe7adfeb2cbf6796d2fe3adf5d17b))
* **ci:** pair the shipped Node with the pinned wrangler, and check it ([#109](https://github.com/forkwright/typikon/issues/109)) ([3ff55dd](https://github.com/forkwright/typikon/commit/3ff55dd814cd29a1680cc98e135d5c8dd10f5231)), closes [#58](https://github.com/forkwright/typikon/issues/58)
* **ci:** pin the transport on toolchain downloads ([#80](https://github.com/forkwright/typikon/issues/80)) ([d6a42ef](https://github.com/forkwright/typikon/commit/d6a42eff9e13dddf9d59ac0e218548c17787a95f))
* **ci:** pin wrangler, and make rendered template headers true ([#93](https://github.com/forkwright/typikon/issues/93)) ([bb1241e](https://github.com/forkwright/typikon/commit/bb1241efafde46b1cb3c1ef8a479cc216c3dcc9b))
* **ci:** refuse lifecycle scripts on the wrangler install, pin the browser gate tools ([#96](https://github.com/forkwright/typikon/issues/96)) ([0e44b2b](https://github.com/forkwright/typikon/commit/0e44b2b4650eae37572ba4724a358f335e9364df)), closes [#58](https://github.com/forkwright/typikon/issues/58)
* **ci:** replace the line-regex CSP gate with an HTML-aware scanner ([#111](https://github.com/forkwright/typikon/issues/111)) ([8e569de](https://github.com/forkwright/typikon/commit/8e569de5827e26cdf0438797e9973e0c345c3440))
* **ci:** require deploy control files and assert the CF branch mutation ([#112](https://github.com/forkwright/typikon/issues/112)) ([3175b1c](https://github.com/forkwright/typikon/commit/3175b1c282212eb99bc9098beeb6d81427fe8257))
* **ci:** serve a loopback-base_url build to browser-based gates ([#46](https://github.com/forkwright/typikon/issues/46)) ([faaa36f](https://github.com/forkwright/typikon/commit/faaa36fe6f0c492d4c63b242616860977101de02)), closes [#29](https://github.com/forkwright/typikon/issues/29)
* **ci:** stop skipping playwright when a consumer ships no smoke specs ([#123](https://github.com/forkwright/typikon/issues/123)) ([48383d8](https://github.com/forkwright/typikon/commit/48383d8029cfa94dc6bbde7c4ddb5872412117cb))
* **ci:** stop the CSP gate crying wolf and the pinning check skipping silently ([#102](https://github.com/forkwright/typikon/issues/102)) ([d6aa4c1](https://github.com/forkwright/typikon/commit/d6aa4c191a73ee1d523841e97d2f3c985decf6a5))
* **ci:** use lychee --root-dir for root-relative resolution ([89e3638](https://github.com/forkwright/typikon/commit/89e3638efc684a06d94c05ccb832e76b7d954e3c))
* **css:** add missing classes + repair undefined token reference ([4856764](https://github.com/forkwright/typikon/commit/485676421bd7ff4e968503bdf11d9bb7a15e3be4))
* **css:** restore .product-shipping margin to --space-2xs ([16995aa](https://github.com/forkwright/typikon/commit/16995aa0cec4666545833d379d02ea7a28615556))
* fan wave — eight reviewed drain fixes + sample-blog asset/lint debt ([#25](https://github.com/forkwright/typikon/issues/25)) ([#40](https://github.com/forkwright/typikon/issues/40)) ([9692994](https://github.com/forkwright/typikon/commit/96929949adc3e82834ba87d47b4b2ed310207e09))
* **fonts:** make the declared Greek coverage checkable ([#115](https://github.com/forkwright/typikon/issues/115)) ([035993d](https://github.com/forkwright/typikon/commit/035993dee9b0849f5d4105cbd97dcde4ccdc6a58))
* **gate-attestation:** bind Gate-Passed check to PR tip commit ([#43](https://github.com/forkwright/typikon/issues/43)) ([9eb14f7](https://github.com/forkwright/typikon/commit/9eb14f7dfddb794ec07680d670bd60f57a92ae8b)), closes [#2399](https://github.com/forkwright/typikon/issues/2399)
* **gate:** a rate limit is not link rot ([#78](https://github.com/forkwright/typikon/issues/78)) ([4341bf8](https://github.com/forkwright/typikon/commit/4341bf8856b98f66da8cef1b5cd7dc808d1831c6))
* **gate:** capture the log a failure points at, and stop leaking the server ([#103](https://github.com/forkwright/typikon/issues/103)) ([402b829](https://github.com/forkwright/typikon/commit/402b829ce6c5274debe1115d5d66ca6ab29eefe6))
* **gate:** make the local gate fail closed and prove browser-stage readiness ([#116](https://github.com/forkwright/typikon/issues/116)) ([d7b2941](https://github.com/forkwright/typikon/commit/d7b2941ad3636ecbbbe1a1a46e87aa835fb8d544))
* **gate:** stop the internal-link stage from failing on a third party ([#77](https://github.com/forkwright/typikon/issues/77)) ([a3948aa](https://github.com/forkwright/typikon/commit/a3948aa74950cdb4e38b80a1a875aae0c340dc68))
* **journal-entry:** swap prev/next to match older=prev convention ([3404046](https://github.com/forkwright/typikon/commit/340404630bdf4b9eb488e02801311cf17fa8a344))
* **layout:** flatten theme dir to repo root (Zola convention) ([b312010](https://github.com/forkwright/typikon/commit/b312010f25e89c7376ea128872beca33be38bfed))
* **migrate:** stop the fallback serializer relocating, corrupting, and aborting ([#101](https://github.com/forkwright/typikon/issues/101)) ([f93f525](https://github.com/forkwright/typikon/commit/f93f525e0f893a49828a14c173ae09e1b6c80f4c))
* **product:** render product metadata and unify sizing-table cells ([#114](https://github.com/forkwright/typikon/issues/114)) ([af5cac5](https://github.com/forkwright/typikon/commit/af5cac50b4d12874848c764b112570eb05012fe7))
* **refresh:** let a consumer decline a specific rendered target ([#105](https://github.com/forkwright/typikon/issues/105)) ([0b90bd7](https://github.com/forkwright/typikon/commit/0b90bd717ce160158b036bec398c5a863b777961))
* **round2:** a11y focus, triad aria/lang, CSP tightening, 404 + feed discovery ([da04f32](https://github.com/forkwright/typikon/commit/da04f320c25bcaca1b409fa2dd610a69cecb06fc))
* **templates+ci:** root-relative asset paths so lychee can verify locally ([41bd7e1](https://github.com/forkwright/typikon/commit/41bd7e1e181dac291819f9393c42faca2e3b27ff))
* **templates:** assert FAQ permalink accessible names on the accessibility tree ([#121](https://github.com/forkwright/typikon/issues/121)) ([d3890e0](https://github.com/forkwright/typikon/commit/d3890e0f663658d637b6814d426be13c6770c4fb)), closes [#61](https://github.com/forkwright/typikon/issues/61)
* **templates:** close product-schema gap and drop invented HowTo duration ([#107](https://github.com/forkwright/typikon/issues/107)) ([6072ada](https://github.com/forkwright/typikon/commit/6072adabef0f3ef1c4a2479876b64cb4933e104b))
* **templates:** delegate page-vs-section context via Tera blocks ([608c9c5](https://github.com/forkwright/typikon/commit/608c9c5d9242c560f01fb5e34b0d256426d9756d))
* **templates:** fixture-prove sourced HowTo duration reproduces exactly ([#120](https://github.com/forkwright/typikon/issues/120)) ([09a4512](https://github.com/forkwright/typikon/commit/09a451295ae23d84c10a0deb5b236350aac9f4f4)), closes [#59](https://github.com/forkwright/typikon/issues/59)
* **templates:** mark dynamic href/src attribute values as safe ([d31eeac](https://github.com/forkwright/typikon/commit/d31eeac7f8f06dff0d02ff68b4198a2e5e1979a1))
* **validate:** enforce the formats the schemas declare ([#108](https://github.com/forkwright/typikon/issues/108)) ([7e588a3](https://github.com/forkwright/typikon/commit/7e588a34c905ddab087baf140604c1b7a9d5d557))

## Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project follows semantic versioning.

No version has been cut yet — everything below is unreleased work on `main`. Once release-please automation is wired (RELEASES.md § Required configuration files), version cuts populate this file with dated, tagged sections below `## Unreleased`.

## Unreleased

### Features

- **ci**: Scaffold kanon deploy template (#17) — consumer sites now scaffold `.kanon-ci.toml` from `ci/kanon-ci.toml.tmpl` with full 14-stage pipeline (zola, CSP, links, a11y, playwright smoke). Dual-CI migration window: forge is primary, GitHub is fallback until forge deploy path validates end-to-end.
- **bin**: Add `typikon-migrate-template` binary — skeleton for schema-migration scripts when frontmatter evolves incompatibly. Consumer sites run this once per major typikon bump.
- **templates**: Enforce required metadata (#2) — frontmatter validation now runs pre-commit.

### Fixes

- **ci**: Drive typikon CI to green (#27) — lychee excludes self-host URLs to break the deploy chicken-and-egg.
- **ci**: Suppress SHELL/strict-mode with intent directive (#15) — `ci/csp-enforce.sh` preserves full-report CSP scan behavior (accumulate violations, do not abort on first miss).
- **lint**: Drop stale CSP inline ignore — follow-up to #18.

### Documentation

- **README**: Add `typikon-migrate-template` to binary inventory (#14).
- **CLAUDE.md**: Add preamble with scope/defers_to/tightens per kanon CONTEXT/preamble-required.

### Changed

- **repo**: Align with FLEET-REPO-SETUP standard (forge-primary) (#13) — add .gitattributes with markdown trailing-whitespace carve-out (D-055), bootstrap empty CHANGELOG.md.
- **lint**: Preserve typikon prose voice — scoped `.kanon-lint-ignore` for typikon#9 (substrate/example prose) and typikon#15 (CSP scan full-report behavior). Per operator decision, em-dash policy is intentional and preserved.
