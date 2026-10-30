(function () {
  "use strict";

  const COLUMNS = [
    "Issue link", "Title", "Created time", "Last updated time", "Priority", "verdict", "PR",
  ];

  function parseCSV(text) {
    const rows = [];
    let row = [];
    let field = "";
    let quoted = false;
    let closedQuote = false;
    text = text.replace(/^\uFEFF/, "");

    function endField() {
      row.push(field);
      field = "";
      closedQuote = false;
    }

    function endRow() {
      endField();
      if (row.some(value => value !== "")) rows.push(row);
      row = [];
    }

    for (let i = 0; i < text.length; i++) {
      const character = text[i];
      if (quoted) {
        if (character === '"') {
          if (text[i + 1] === '"') {
            field += '"';
            i++;
          } else {
            quoted = false;
            closedQuote = true;
          }
        } else {
          field += character;
        }
      } else if (character === ",") {
        endField();
      } else if (character === "\r" || character === "\n") {
        if (character === "\r" && text[i + 1] === "\n") i++;
        endRow();
      } else if (character === '"' && field === "" && !closedQuote) {
        quoted = true;
      } else {
        if (closedQuote || character === '"') throw new Error("Invalid CSV quoting.");
        field += character;
      }
    }
    if (quoted) throw new Error("The CSV ends inside a quoted field.");
    if (field !== "" || row.length || closedQuote) endRow();
    return rows;
  }

  function parseIssueRecords(text) {
    const [headers, ...rows] = parseCSV(text);
    if (!headers || COLUMNS.some(column => !headers.includes(column))) {
      throw new Error(`Choose a triage CSV with these columns: ${COLUMNS.join(", ")}.`);
    }
    if (new Set(headers).size !== headers.length) throw new Error("The CSV has duplicate column names.");
    return rows.map((row, index) => {
      if (row.length !== headers.length) {
        throw new Error(`CSV record ${index + 2} has ${row.length} columns; expected ${headers.length}.`);
      }
      return Object.fromEntries(headers.map((header, i) => [header, row[i]]));
    });
  }

  function normalizeIssues(issues) {
    if (!Array.isArray(issues)) throw new Error("Expected an array of issues.");
    return issues.map(record => {
      if (!record || COLUMNS.some(column => typeof record[column] !== "string")) {
        throw new Error("Issue record has invalid or missing columns.");
      }
      const issue = { ...record };
      // CSV exports escape spreadsheet formulas; textContent safely displays the original title.
      if (/^'(?:[\t\r\n]|\s*[=+\-@])/.test(issue.Title)) issue.Title = issue.Title.slice(1);
      return issue;
    });
  }

  function parseIssues(text) {
    return normalizeIssues(parseIssueRecords(text));
  }

  const api = { COLUMNS, parseCSV, parseIssueRecords, normalizeIssues, parseIssues };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalThis.TriageIssues = api;
  }
})();
