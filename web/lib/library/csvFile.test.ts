import { describe, expect, it } from "vitest";
import { CsvFileProblem, MAX_CSV_BYTES, readCsvFile } from "./csvFile";

function csv(name: string, text: string): File {
  return new File([text], name, { type: "text/csv" });
}

describe("readCsvFile (TM11-55)", () => {
  it("returns the text of a CSV", async () => {
    expect(await readCsvFile(csv("library.csv", "title\nHades\n"))).toBe("title\nHades\n");
  });

  it("accepts an upper-case extension", async () => {
    expect(await readCsvFile(csv("LIBRARY.CSV", "title\n"))).toBe("title\n");
  });

  it("refuses a file that isn't a .csv", async () => {
    await expect(readCsvFile(csv("library.xlsx", "title\n"))).rejects.toThrow(
      new CsvFileProblem("Choose a .csv file."),
    );
  });

  it("refuses an empty file", async () => {
    await expect(readCsvFile(csv("library.csv", ""))).rejects.toThrow("The file is empty.");
  });

  it("refuses a file over the size limit before reading it", async () => {
    const big = csv("library.csv", "x".repeat(MAX_CSV_BYTES + 1));
    await expect(readCsvFile(big)).rejects.toThrow("larger than 1 MB");
  });
});
