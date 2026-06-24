/**
 * Intern Feed — Applied-jobs sync backend (Google Apps Script).
 *
 * Receives applied-job records from the static Intern Feed page and writes them
 * into the bound Google Sheet (tab "Applied"). One row per job, keyed by `id`,
 * so re-sends update the same row instead of duplicating it.
 *
 * Deploy as: Web app, Execute as "Me", Who has access "Anyone".
 * See SETUP.md for the full walkthrough.
 */

var SHEET_NAME = 'Applied';
var HEADERS = ['id', 'company', 'role', 'status', 'applied_date', 'notes', 'location', 'apply_url', 'updated_at'];

function doPost(e) {
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(30000);
  } catch (err) {
    return json_({ ok: false, error: 'busy' });
  }
  try {
    var sh = getSheet_();
    var body = JSON.parse(e.postData.contents);
    if (body.type === 'delete') {
      deleteById_(sh, body.id);
    } else if (body.type === 'bulk') {
      (body.records || []).forEach(function (r) { upsert_(sh, r); });
    } else { // 'upsert' (default)
      upsert_(sh, body.record);
    }
    return json_({ ok: true });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

// Simple health check so visiting the URL in a browser confirms it's live.
function doGet() {
  return json_({ ok: true, service: 'intern-feed-applied', rows: Math.max(getSheet_().getLastRow() - 1, 0) });
}

function getSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
  if (sh.getLastRow() === 0) {
    sh.appendRow(HEADERS);
    sh.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

function findRow_(sh, id) {
  var n = sh.getLastRow() - 1;
  if (n <= 0) return -1;
  var ids = sh.getRange(2, 1, n, 1).getValues();
  for (var i = 0; i < ids.length; i++) {
    if (String(ids[i][0]) === String(id)) return i + 2;
  }
  return -1;
}

function upsert_(sh, r) {
  if (!r || !r.id) return;
  var row = [
    r.id, r.company || '', r.role || '', r.status || 'applied',
    r.applied_date || '', r.notes || '', r.location || '', r.apply_url || '',
    r.updated_at || new Date().toISOString()
  ];
  var n = findRow_(sh, r.id);
  if (n > 0) sh.getRange(n, 1, 1, row.length).setValues([row]);
  else sh.appendRow(row);
}

function deleteById_(sh, id) {
  var n = findRow_(sh, id);
  if (n > 0) sh.deleteRow(n);
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
