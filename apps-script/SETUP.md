# Applied-jobs → Google Sheet sync (one-time setup)

The Intern Feed page is fully static, so it can't write to Google Sheets on its
own. This bridges that gap with a tiny **Google Apps Script web app** — a free
backend bound to a Sheet that you own. Once set up, every time you click
**+ applied** (or change a status / notes), the page pushes that row into your
Sheet, which becomes your permanent tracker you can open from any device.

You only do this once. Takes about 5 minutes.

---

## 1. Create the Sheet

1. Go to <https://sheets.google.com> and create a new blank spreadsheet.
2. Name it something like **"Internship Applications"**.
   (You don't need to add headers — the script creates an `Applied` tab with
   headers automatically on the first sync.)

## 2. Add the script

1. In that Sheet, click **Extensions → Apps Script**.
2. Delete whatever is in the editor, then paste the entire contents of
   **`Code.gs`** (in this folder) into it.
3. Click the **Save** icon (💾).

## 3. Deploy it as a web app

1. Click **Deploy → New deployment**.
2. Click the gear ⚙ next to "Select type" → choose **Web app**.
3. Set:
   - **Description:** anything (e.g. "intern feed sync")
   - **Execute as:** **Me** (your account)
   - **Who has access:** **Anyone**
     *(This means anyone with the long random URL can POST to it. The URL is
     unguessable; only your browser knows it. If you'd rather lock it down, see
     "Locking it down" below.)*
4. Click **Deploy**.
5. Google will ask you to **authorize** — click through, pick your account, and
   on the "Google hasn't verified this app" screen choose **Advanced → Go to
   (your project)** → **Allow**. (This is normal for personal scripts.)
6. Copy the **Web app URL**. It looks like:
   `https://script.google.com/macros/s/AKfyc…/exec`

## 4. Connect the page

1. Open the Intern Feed page (`index.html`).
2. Click **⚙ sync** in the top-right.
3. Paste the Web app URL into the box and click **save**.
4. Click **test** — then check your Sheet. A row reading **"(test)"** should
   appear in the `Applied` tab. If it does, sync works. Delete that test row.

That's it. From now on, marking a job **+ applied** writes it to the Sheet, and
changing its status, date, or notes updates the same row. Use **sync all to
sheet** (in the Applied tab) any time you want to push everything at once — e.g.
right after setup, if you'd already marked some jobs.

---

## How it behaves

- **Page → Sheet is one-way.** The page keeps its own copy in the browser, and
  mirrors changes to the Sheet. Editing the Sheet by hand won't flow back into
  the page, so treat the page as where you *make* changes and the Sheet as your
  permanent, portable record.
- **Removing a job** in the Applied tab deletes its row from the Sheet too.
- **No URL set?** Everything still works and persists in the browser — you just
  won't have the cloud copy. The **export CSV** button is always available as a
  manual backup.

## Locking it down (optional)

If "Anyone with the link" makes you uneasy, add a shared secret:

1. In `Code.gs`, near the top of `doPost`, check `body.secret` against a value
   you choose, and reject if it doesn't match.
2. In `index.html`, add that same secret to the payloads (in `pushSyncTo`).

For a personal tracker behind an unguessable URL, this is usually overkill, but
the option is there.

## Updating the script later

If you change `Code.gs`, redeploy with **Deploy → Manage deployments → edit
(pencil) → Version: New version → Deploy**. The URL stays the same, so you don't
need to re-paste it into the page.
