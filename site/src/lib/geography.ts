import type { TaxonomyDto } from '../data-access/catalogApi';

export type GeographyGroups = {
  country: TaxonomyDto[];
  districts: TaxonomyDto[];
  subjects: TaxonomyDto[];
  other: TaxonomyDto[];
};

const federalDistrictSlugs = new Set([
  'central',
  'northwestern',
  'volga',
  'southern',
  'north-caucasian',
  'ural',
  'siberian',
  'far-eastern'
]);

const federalDistrictNames = new Map([
  ['центральный', 'central'],
  ['северо-западный', 'northwestern'],
  ['приволжский', 'volga'],
  ['южный', 'southern'],
  ['северо-кавказский', 'north-caucasian'],
  ['уральский', 'ural'],
  ['сибирский', 'siberian'],
  ['дальневосточный', 'far-eastern']
]);

function canonicalDistrictSlug(option: TaxonomyDto): string | null {
  const slug = option.slug.trim().toLowerCase();
  if (federalDistrictSlugs.has(slug)) return slug;
  const normalizedName = option.name
    .replace(/\s+федеральный\s+округ$/iu, '')
    .trim()
    .toLocaleLowerCase('ru-RU');
  return federalDistrictNames.get(normalizedName) ?? null;
}

function sortOptions(options: TaxonomyDto[]): TaxonomyDto[] {
  return options.sort((left, right) => left.name.localeCompare(right.name, 'ru'));
}

/**
 * Groups the flat API taxonomy into a clear country / federal district /
 * subject presentation without changing the public API contract.
 */
export function groupGeographies(options: readonly TaxonomyDto[]): GeographyGroups {
  const unique = new Map<string, TaxonomyDto>();
  for (const option of options) {
    const districtSlug = canonicalDistrictSlug(option);
    const canonical = districtSlug
      ? { slug: districtSlug, name: option.name.replace(/\s+федеральный\s+округ$/iu, '').trim() }
      : option;
    unique.set(canonical.slug, canonical);
  }

  const groups: GeographyGroups = { country: [], districts: [], subjects: [], other: [] };
  for (const option of unique.values()) {
    if (option.slug === 'russia' || option.name === 'Россия' || option.name === 'Российская Федерация') {
      groups.country.push(option);
    } else if (canonicalDistrictSlug(option)) {
      groups.districts.push(option);
    } else if (option.name.trim()) {
      groups.subjects.push(option);
    } else {
      groups.other.push(option);
    }
  }
  sortOptions(groups.country);
  sortOptions(groups.districts);
  sortOptions(groups.subjects);
  sortOptions(groups.other);
  return groups;
}
