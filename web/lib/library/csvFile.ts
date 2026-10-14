// Read a CSV the user picked, before it is sent for review (TM11-55, REQ004).
//
// These checks only exist to give a fast, clear message. The server enforces
// the same limits and more (api/services/library_csv.py), so nothing here is
// trusted: a renamed or edited file still gets checked there.

/** Same value as MAX_CSV_BYTES in api/services/library_csv.py. */
export const MAX_CSV_BYTES = 1_000_000;

/** A problem with the picked file. `message` is written for the user. */
export class CsvFileProblem extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CsvFileProblem";
  }
}

export async function readCsvFile(file: File): Promise<string> {
  if (!file.name.toLowerCase().endsWith(".csv")) {
    throw new CsvFileProblem("Choose a .csv file.");
  }
  if (file.size === 0) {
    throw new CsvFileProblem("The file is empty.");
  }
  if (file.size > MAX_CSV_BYTES) {
    throw new CsvFileProblem("The file is larger than 1 MB. Split it and upload each part.");
  }
  return file.text();
}
