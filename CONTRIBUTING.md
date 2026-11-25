# Contributing to LuxOS

Thanks for helping. Bugs and ideas go to [GitHub issues](https://github.com/luxopes/LuxOS-Arch/issues)
or the Feedback app in LuxOS; code goes in as a pull request against `main`.

## How LuxOS is developed: AI-assisted, human-reviewed

LuxOS is built with heavy use of AI coding assistants. We say it openly because it is how the project
moves as fast as it does.

What that means in practice:

- **A person is responsible for every change.** The maintainer reads, builds and tries every change
  before it is released, and answers for its quality — no matter who or what wrote it.
- **Every change comes with tests**, and a test must fail without the change. "It compiles" is not a test.
- **Every change is used for real before a release:** in a VM or on hardware, by clicking through it,
  not only by automated tests.
- **Security-sensitive parts get a manual review line by line:** the compositor (`packages/luxcomp`,
  `packages/luxwm`), login and lock (PAM, `luxos-greetd`, `luxos-lock`), the app sandbox, `lux` and
  updates, Lux Guard, drivers and signing.
- **Releases go through `staging` first**, and only then to `stable`.
- **Commits name a human author.** Tools are tools; they are not co-authors.

## Pull requests from contributors

You are welcome to use AI tools too. The same rules apply to you:

1. You are responsible for what you submit. Understand your change and be able to explain it.
2. Keep it focused: one problem per pull request, no unrelated reformatting.
3. Add or update tests, and say what you tested and how (VM, hardware, which LuxOS version).
4. Write plain, readable code — the simplest construct that works, no boilerplate. Comments explain
   *why*, not *what*.
5. Never add telemetry, network calls, new dependencies or binaries without saying so in the
   description.
6. New desktop code is written in [LSL](https://lsl.lux-ai.cz); C only where LSL cannot do it.
   No new Python in the desktop.

Every pull request is reviewed and approved by the maintainer before it is merged. Changes to
security-sensitive parts (list above) need a closer review and may take longer.

## Reporting a security problem

Please do not open a public issue. Write to <info@lux-ai.cz> with the details; you will get an answer.
