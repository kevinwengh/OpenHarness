# Documentation localization policy

English is the canonical language for source-level and operational documentation. The translated
`README.zh-CN.md` is a concise project entry point, not a second independently maintained reference
tree.

When changing a user-visible name, installation command, supported platform, built-in capability
count, or primary navigation link in `README.md`, update the corresponding translated statement in
`README.zh-CN.md` in the same pull request. Technical deep dives should link to the canonical
English document until a named maintainer owns a complete translation.

Do not machine-translate security guarantees, destructive commands, migration steps, or
compatibility promises without review by a fluent maintainer. A partial translation must say that
the English document is authoritative and link to it.

The documentation integrity check validates local links in both READMEs but does not assess
semantic translation parity. Reviewers own that judgment.
