# Quote Desk

Small Flask application with its existing HTML frontend. Keep this structure and stack.

## Running on Replit

Dependencies are listed in `requirements.txt`.
Run regression checks with `python3 -m unittest discover -s tests`.
No public workflow is configured: the current app has no authentication and can access a connected Gmail mailbox and customer orders. Add sign-in and authorization before exposing a preview or publishing it.
The existing local development entry point remains `python3 app.py` (localhost port 5070).

## Service configuration

- `ALLWHERE_AUTH`: Authorization header (for example, a Basic or Bearer header), a `username:password` pair, or a serialized two-string list/tuple. Legacy `ALLWHERE_USER` and `ALLWHERE_PASS` are still supported when `ALLWHERE_AUTH` is absent.
- `ALLWHERE_BASE`: Allwhere service URL, either the root or ending in `/v1` or `/v2`. The existing production service URL remains the default when unset.
- `GMAIL_TOKEN_JSON`: Gmail authorized-user token JSON.
- Optional `PS_USER` and `PS_PASS`: product-service catalog lookup credentials.
- Optional `SCOUT_URL`: enables the desktop Scout-only features. Those buttons stay hidden when unset.

Never print credentials or put them in source control. Gmail drafts and sends are real actions; preserve the existing send confirmation and existing-thread/draft guard.
