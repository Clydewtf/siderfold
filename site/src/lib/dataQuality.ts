import type { DataQuality, DataQualityField, SupportProgram } from '../types';

type ProgramQualityInput = Omit<SupportProgram, 'dataQuality'>;

function hasFunding(program: ProgramQualityInput): boolean {
  return (
    typeof program.fundingAmountRub === 'number' ||
    typeof program.fundingMinRub === 'number' ||
    typeof program.fundingMaxRub === 'number'
  );
}

export function calculateProgramDataQuality(program: ProgramQualityInput): DataQuality {
  const missingFields: DataQualityField[] = [];

  if (!hasFunding(program)) missingFields.push('funding');
  if (program.deadline === null) missingFields.push('deadline');
  if (program.regions.length === 0) missingFields.push('regions');
  if (program.sourceId.trim().length === 0) missingFields.push('source');
  if (program.updatedAt.trim().length === 0) missingFields.push('updatedAt');
  if (program.sourceUrl.trim().length === 0) missingFields.push('sourceUrl');

  const score = Math.round(((6 - missingFields.length) / 6) * 100);
  const level = score >= 84 ? 'high' : score >= 50 ? 'medium' : 'low';

  return {
    score,
    level,
    missingFields,
    checkedAt: program.updatedAt || 'unknown'
  };
}
