/**
 * Platform availability field mapping (REQ008).
 * Normalizes raw storefront strings (IGDB/RAWG-style, inconsistent
 * casing/naming) to PlatformType, populates availablePlatforms per game,
 * and reports how much of the source data actually mapped.
 */

// OTHER is a first-class member, not a dropped value — unrecognized
// strings land here instead of vanishing.
const PlatformType = Object.freeze({
  STEAM: "STEAM",
  XBOX: "XBOX",
  EPIC: "EPIC",
  PSN: "PSN",
  OTHER: "OTHER",
});

// Known source strings -> enum. Extend as new variants show up.
const ALIAS_MAP = {
  steam: PlatformType.STEAM,
  "pc (steam)": PlatformType.STEAM,

  xbox: PlatformType.XBOX,
  "xbox one": PlatformType.XBOX,
  "xbox series x": PlatformType.XBOX,
  "xbox series s": PlatformType.XBOX,
  "xbox series x|s": PlatformType.XBOX,
  "xbox 360": PlatformType.XBOX,

  "epic games store": PlatformType.EPIC,
  "epic games": PlatformType.EPIC,
  epic: PlatformType.EPIC,

  playstation: PlatformType.PSN,
  "playstation 4": PlatformType.PSN,
  "playstation 5": PlatformType.PSN,
  ps4: PlatformType.PSN,
  ps5: PlatformType.PSN,
  psn: PlatformType.PSN,
};

/**
 * Normalizes one raw storefront string to a PlatformType (OTHER if unrecognized).
 * @param {string} raw
 * @returns {string}
 */
function normalizePlatform(raw) {
  const key = String(raw || "").trim().toLowerCase();
  return ALIAS_MAP[key] || PlatformType.OTHER;
}

/**
 * Populates availablePlatforms on a game from its raw storefront list.
 * Keeps unmapped raw values too, so OTHER classifications stay auditable.
 *
 * @param {{title: string, rawStorefronts: string[]}} game
 * @returns {{title: string, rawStorefronts: string[], availablePlatforms: string[], unmapped: string[]}}
 */
function mapGamePlatforms(game) {
  const rawStorefronts = game.rawStorefronts || [];
  const mapped = rawStorefronts.map((raw) => ({ raw, type: normalizePlatform(raw) }));

  const availablePlatforms = [...new Set(mapped.map((m) => m.type))];
  const unmapped = mapped.filter((m) => m.type === PlatformType.OTHER).map((m) => m.raw);

  return { ...game, availablePlatforms, unmapped };
}

/**
 * Reports how much of a catalog mapped to a known PlatformType, so the
 * UI's "unknown platform" fallback can cite a real number.
 *
 * @param {Array} games - games already run through mapGamePlatforms
 * @returns {{totalGames: number, gamesWithKnownPlatform: number, coveragePercent: number, unmappedSamples: string[]}}
 */
function computeCoverage(games) {
  const totalGames = games.length;
  const gamesWithKnownPlatform = games.filter((g) =>
    g.availablePlatforms.some((p) => p !== PlatformType.OTHER)
  ).length;

  const coveragePercent = totalGames === 0 ? 0 : Math.round((gamesWithKnownPlatform / totalGames) * 1000) / 10;

  // Sample of unrecognized strings, capped — useful for spotting new
  // source variants to add to ALIAS_MAP.
  const unmappedSamples = [...new Set(games.flatMap((g) => g.unmapped))].slice(0, 10);

  return { totalGames, gamesWithKnownPlatform, coveragePercent, unmappedSamples };
}

module.exports = { PlatformType, normalizePlatform, mapGamePlatforms, computeCoverage };

// ---------------------------------------------------------------------
// Self-test — run with `node platform-availability-mapping.js`.
// ---------------------------------------------------------------------
if (require.main === module) {
  const rawCatalog = [
    { title: "Baldur's Gate 3", rawStorefronts: ["Steam", "PlayStation 5", "Xbox Series X|S"] },
    { title: "Hades", rawStorefronts: ["PC (Steam)", "Epic Games Store"] },
    { title: "Some Indie Game", rawStorefronts: ["itch.io"] }, // fully unmapped
    { title: "Forza Horizon 5", rawStorefronts: ["Xbox One", "PC (Steam)"] },
  ];

  const mappedCatalog = rawCatalog.map(mapGamePlatforms);
  const coverage = computeCoverage(mappedCatalog);

  console.log(JSON.stringify(mappedCatalog, null, 2));
  console.log(coverage);

  console.assert(mappedCatalog[0].availablePlatforms.includes(PlatformType.STEAM), "BG3 should map Steam");
  console.assert(mappedCatalog[2].availablePlatforms[0] === PlatformType.OTHER, "itch.io should be OTHER");
  console.assert(coverage.totalGames === 4, "should count all 4 games");
  console.assert(coverage.gamesWithKnownPlatform === 3, "3 of 4 games have a known platform");
  console.assert(coverage.coveragePercent === 75, "coverage should be 75%");
  console.log("Self-test passed.");
}