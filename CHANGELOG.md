# Changelog

All notable changes to the skills in this repository are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/), and skill versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## lawyer-video 0.1.0 - 2026-11-02

First public release.

- List the avatars and voices of a certified lawyer the API key is authorized for
- Submit a script (up to 300 characters) and wait for the talking-head video; returns a watch link and a download link
- The agent asks for the API key, explains the risks, verifies it and saves it locally with `configure`
- Signed requests with automatic clock-skew correction, and an idempotency key for safe submit retries
