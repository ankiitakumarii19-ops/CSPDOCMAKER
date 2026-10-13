/**
 * CSPdocMaker — show each CSP's photo as a real picture in the Photo column.
 * (Tracker No. 91; set-up steps: deploy/SHEET-PHOTOS.md)
 *
 * The app writes  =IMAGE("https://indev.eko.in/csp-docmaker/api/public/photos/…")
 * into a CSP's Photo cell whenever it gets or changes their photo. That link
 * works for one day. Every 5 minutes this script replaces each such formula
 * with a real in-cell picture, which Google stores itself — so the cell keeps
 * the photo, with no link left in it.
 *
 * Install once: Extensions → Apps Script → paste this file → Save →
 * choose "installTrigger" → Run → allow access. Nothing else to do.
 */

const TABS = ['KOData', 'SUBKOData'];   // the CSP sheet's tabs
const PHOTO_HEADER = 'Photo';
const CODE_HEADER = 'CSP Code';

function convertPhotos() {
  const book = SpreadsheetApp.getActive();
  TABS.forEach(function (tabName) {
    const sheet = book.getSheetByName(tabName);
    if (!sheet || sheet.getLastRow() < 2) return;

    const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0]
      .map(function (h) { return String(h).trim(); });
    const photoCol = header.indexOf(PHOTO_HEADER) + 1;
    const codeCol = header.indexOf(CODE_HEADER) + 1;
    if (!photoCol) return;

    const rows = sheet.getLastRow() - 1;
    const formulas = sheet.getRange(2, photoCol, rows, 1).getFormulas();
    const codes = codeCol ? sheet.getRange(2, codeCol, rows, 1).getValues() : [];

    formulas.forEach(function (cell, i) {
      const match = /^=IMAGE\("([^"]+)"\)$/i.exec(cell[0] || '');
      if (!match) return;                      // already a picture, or empty
      const code = codes[i] ? String(codes[i][0]).trim() : '';
      try {
        const picture = SpreadsheetApp.newCellImage()
          .setSourceUrl(match[1])
          .setAltTextTitle(code ? 'Photo of CSP ' + code : 'CSP photo')
          .build();
        sheet.getRange(i + 2, photoCol).setValue(picture);
      } catch (e) {
        // Left as the formula (it still shows the photo) and tried again on
        // the next run.
        console.warn(tabName + ' row ' + (i + 2) + ': ' + e);
      }
    });
  });
}

/** Run once: makes convertPhotos run every 5 minutes. */
function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'convertPhotos') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('convertPhotos').timeBased().everyMinutes(5).create();
  convertPhotos();
}
