/**
 * @jest-environment node
 *
 * The job-status proxy serves two consumers with different needs: the 2s
 * progress poll (wants three numbers) and restore, which rebuilds the whole
 * editor (wants the extraction and the translated runs).
 *
 * Both shapes are pinned here because getting it wrong is not obvious at a
 * glance: trimming the record made restore hand the editor a document with no
 * slides, so translating threw "x.slides is not iterable"; and a poll response
 * that silently omits translated_runs overwrote a finished translation with an
 * empty list, which made the results vanish right after they appeared.
 */
import { NextRequest } from 'next/server';
import { GET } from '../app/api/jobs/[job_id]/route';

const backendRecord = {
  job_id: 'job-1',
  filename: 'hiauto-post-sept-physical-ai-gl.pptx',
  status: 'completed',
  progress: 100,
  total_runs: 241,
  translated_runs: [
    { run_id: 'run_0_13_0_0_1397', original_text: 'PHASE 2 PROPOSAL', translated_text: 'フェーズ2提案書' },
  ],
  slides: [
    {
      slide_index: 0,
      slide_id: 'slide-0',
      text_boxes: [
        {
          box_id: 'box-0-13',
          shape_index: 13,
          runs: [{ run_id: 'run_0_13_0_0_1397', text: 'PHASE 2 PROPOSAL' }],
        },
      ],
    },
  ],
  error: null,
};

function mockBackend(record: unknown = backendRecord, ok = true, status = 200) {
  global.fetch = jest.fn(async () => ({
    ok,
    status,
    json: async () => record,
  })) as unknown as typeof fetch;
}

function call(qs = '') {
  return GET(new NextRequest(`http://localhost:3000/api/jobs/job-1${qs}`), {
    params: Promise.resolve({ job_id: 'job-1' }),
  });
}

describe('job status proxy', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('keeps the polling response lightweight', async () => {
    mockBackend();
    const body = await (await call()).json();
    expect(Object.keys(body).sort()).toEqual(['progress', 'status', 'total_runs']);
  });

  it('returns the extraction and the translated runs for restore', async () => {
    mockBackend();
    const body = await (await call('?full=1')).json();
    expect(body.filename).toBe('hiauto-post-sept-physical-ai-gl.pptx');
    expect(body.total_slides).toBe(1);
    expect(body.slides).toHaveLength(1);
    expect(body.slides[0].text_boxes[0].runs[0].run_id).toBe('run_0_13_0_0_1397');
    expect(body.translated_runs).toHaveLength(1);
  });

  it('never returns undefined slides or runs on a partial record', async () => {
    mockBackend({ job_id: 'job-1', status: 'processing' });
    const body = await (await call('?full=1')).json();
    expect(body.slides).toEqual([]);
    expect(body.total_slides).toBe(0);
    expect(body.translated_runs).toEqual([]);
  });

  it('surfaces backend failures instead of inventing a record', async () => {
    mockBackend({}, false, 404);
    const res = await call();
    expect(res.status).toBe(404);
    expect((await res.json()).error).toBe('Job not found');
  });
});
