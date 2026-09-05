# Assets

Drop the logo files here with these exact names. Until they exist the hub falls
back to Anton type, which looks fine.

| File | What |
|---|---|
| `mark.svg` | the C monogram |
| `wordmark.svg` | the CULTSIDERS lockup |

PNG works too — just change the extension in the two `<img>` tags at the top of
`index.html`.

## One file covers both themes

Upload the **black-on-white** version. The hub applies `filter: invert(1)` in
dark mode, so black-on-white becomes white-on-black automatically. There is no
need to make or maintain a second file.

The white rectangle showing behind the logo in light mode is intentional.

## Adding them

Easiest path is the browser, no git needed: open the repo, go into `assets/`,
**Add file → Upload files**, drag both in, commit.
