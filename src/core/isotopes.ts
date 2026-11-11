// A reference isotope for every element, so a model of an atom can always show how many protons and neutrons its nucleus holds.
// For an element with a stable or long-lived natural isotope it is the most abundant natural isotope; for an element with none (technetium,
// promethium and everything after bismuth except thorium and uranium) it is a commonly cited long-lived isotope. It is a labelled choice for the
// picture, not a measurement, and it is never derived by rounding the atomic weight.
const MASS_NUMBER: readonly number[] = [
  0,
  1, 4,                                                                                          // H He
  7, 9, 11, 12, 14, 16, 19, 20,                                                                  // Li - Ne
  23, 24, 27, 28, 31, 32, 35, 40,                                                                // Na - Ar
  39, 40, 45, 48, 51, 52, 55, 56, 59, 58, 63, 64, 69, 74, 75, 80, 79, 84,                        // K - Kr
  85, 88, 89, 90, 93, 98, 98, 102, 103, 106, 107, 114, 115, 120, 121, 130, 127, 132,             // Rb - Xe (Tc 98)
  133, 138, 139, 140, 141, 142, 145, 152, 153, 158, 159, 164, 165, 166, 169, 174, 175,           // Cs - Lu (Pm 145)
  180, 181, 184, 187, 192, 193, 195, 197, 202, 205, 208, 209,                                    // Hf - Bi
  209, 210, 222, 223, 226, 227, 232, 231, 238, 237, 244, 243, 247, 247, 251, 252, 257, 258, 259, // Po - No
  266, 267, 268, 269, 270, 269, 278, 281, 282, 285, 286, 289, 290, 293, 294, 294,                // Lr - Og
];
export interface ReferenceIsotope { z: number; a: number; neutrons: number; kind: 'most abundant natural isotope' | 'long-lived isotope' }

export function referenceIsotope(z: number): ReferenceIsotope | null {
  if (!Number.isInteger(z) || z < 1 || z >= MASS_NUMBER.length) return null;
  const natural = z <= 83 ? z !== 43 && z !== 61 : z === 90 || z === 92;
  return { z, a: MASS_NUMBER[z], neutrons: MASS_NUMBER[z] - z, kind: natural ? 'most abundant natural isotope' : 'long-lived isotope' };
}
export const ELEMENT_COUNT = MASS_NUMBER.length - 1;
