# Hermes Collaboration

Hermes may inspect this repository, open implementation questions, and propose
changes through issues and pull requests. It must not retrieve Final Surge
credentials, browser cookies, or calendar contents into issues, logs, or chat.

For work requests, include the target branch, desired behavior, and whether
calendar writes are allowed. A plan or workout write always requires explicit
operator approval in the request that triggers it.

The Homelab vault item is `log.finalsurge.com`; access it only at runtime via
`FinalSurgeClient.from_1password()`. Never copy secret values into a Hermes
environment file or repository configuration.
