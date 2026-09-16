import { mapProgramDetail, type PublicProgram } from '../data-access/catalogMapper';
import type { ProgramDetailDto } from '../data-access/catalogApi';
import type { ReviewPublicPreview } from './api';

export function mapReviewPublicPreview(
  reviewCaseId: string,
  preview: ReviewPublicPreview
): PublicProgram {
  const source = {
    source: preview.source,
    source_url: preview.source_url,
    observed_at: preview.observed_at
  };
  const program: ProgramDetailDto = {
    id: `review-preview:${reviewCaseId}`,
    title: preview.title,
    publication_status: 'published',
    published_at: '',
    updated_at: '',
    source_published_on: preview.source_published_on,
    summary: preview.summary,
    source_status: preview.source_status,
    deadline_on: preview.deadline_on,
    funding: preview.funding,
    primary_source: source,
    sources: [source],
    geographies: preview.geographies,
    themes: preview.themes,
    eligibility_summary: preview.eligibility_summary,
    eligibility_geography_note: preview.eligibility_geography_note,
    access_mode: preview.access_mode,
    application_url: preview.application_url,
    application_start_on: preview.application_start_on,
    application_end_on: preview.application_end_on,
    funding_amounts: preview.funding_amounts,
    timeline: preview.timeline,
    resources: preview.resources,
    content_sections: preview.content_sections
  };
  return mapProgramDetail(program);
}
