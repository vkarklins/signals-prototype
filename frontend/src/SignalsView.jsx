import { useEffect, useState } from 'react';
import './signals.css';

const blank = () => ({name: '', description: '', instruction: '', enabled: false,
  output_schema: '{\n  "type": "object",\n  "properties": {}\n}'});
async function request(path, options = {}) {
  const response = await fetch(`/api/${path}`, { ...options,
    headers: {'Content-Type': 'application/json'}, cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
function TraceLink({url}) {
  return url ? <a href={url} target="_blank" rel="noreferrer">View trace ↗</a> : <span>Trace link not configured</span>;
}
export default function SignalsView({hidden}) {
  const [tab, setTab] = useState('definitions');
  const [signals, setSignals] = useState([]), [rows, setRows] = useState([]);
  const [draft, setDraft] = useState(blank), [editing, setEditing] = useState(null);
  const [offset, setOffset] = useState(0), [run, setRun] = useState('');
  const [refresh, setRefresh] = useState(0), [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  useEffect(() => {
    if (hidden) return;
    let cancelled = false;
    setLoading(true); setError(''); setRows([]);
    const path = tab === 'definitions' ? 'signals' : tab === 'runs'
      ? `signal-runs?limit=50&offset=${offset}`
      : `signal-events?limit=50&offset=${offset}${run ? `&run_id=${encodeURIComponent(run)}` : ''}`;
    request(path).then(data => {if (!cancelled) { if (tab === 'definitions') setSignals(data); else setRows(data); }})
      .catch(e => {if (!cancelled) setError(e.message);})
      .finally(() => {if (!cancelled) setLoading(false);});
    return () => {cancelled = true;};
  }, [hidden, tab, offset, run, refresh]);
  function changeTab(value) {setTab(value); setOffset(0); setRun(''); setNotice('');}
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const payload = {...draft, output_schema: JSON.parse(draft.output_schema)};
      const result = await request(`signals${editing ? `/${editing}` : ''}`, {method: editing ? 'PATCH' : 'POST', body: JSON.stringify(payload)});
      edit(result);
      setNotice(`Saved ${result.name}, version ${result.version}.`); setRefresh(x => x + 1);
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function retry(id) {
    setBusy(true); setError('');
    try {await request(`signal-runs/${id}/retry`, {method: 'POST'}); setNotice('Retry queued. The detection worker will process it.'); setRefresh(x => x + 1);}
    catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  function edit(signal) {
    setEditing(signal.id); setDraft({name: signal.name, description: signal.description,
      instruction: signal.instruction, enabled: signal.enabled, output_schema: JSON.stringify(signal.output_schema, null, 2)});
    setNotice('');
  }
  // Send only editable fields, including after loading a saved response.
  function field(key, value) {setDraft(d => ({...d, [key]: value}));}
  return <main className="page-content signals-page" hidden={hidden}>
    <section className="page-heading"><div><h1>Signals</h1><p className="page-description">Define what to look for. Review what happened.</p></div>
      <button className="secondary-button" disabled={loading || busy} onClick={() => setRefresh(x => x + 1)}>Refresh</button></section>
    <div className="signal-tabs" aria-label="Signal views">{['definitions','runs','events'].map(t => <button key={t} aria-pressed={tab === t} onClick={() => changeTab(t)}>{t[0].toUpperCase()+t.slice(1)}</button>)}</div>
    {error && <p className="error-message" role="alert">{error}</p>}
    {notice && <p role="status" className="results-notice">{notice}</p>}
    {loading && <p role="status">Loading…</p>}
    {tab === 'definitions' ? <div className="signal-layout">
      <section aria-label="Saved Signals"><button className="secondary-button" disabled={busy} onClick={() => {setEditing(null); setDraft(blank());}}>New Signal</button>
        {!loading && !error && !signals.length && <p>No Signals yet. Create one to define what to detect.</p>}
        {signals.map(s => <article className="signal-card" key={s.id}><h2>{s.name}</h2><p>{s.description || 'No description'}</p><p>{s.enabled ? 'Enabled' : 'Disabled'} · Version {s.version}</p><button className="secondary-button" disabled={busy} onClick={() => edit(s)}>Edit {s.name}</button></article>)}</section>
      <form className="signal-editor" onSubmit={save}><h2>{editing ? 'Edit Signal' : 'New Signal'}</h2>
        <label>Name<input required value={draft.name} onChange={e => field('name',e.target.value)} /></label>
        <label>Description<textarea value={draft.description} onChange={e => field('description',e.target.value)} /></label>
        <label>Detection instruction<textarea required rows="6" value={draft.instruction} onChange={e => field('instruction',e.target.value)} /></label>
        <label>Custom fields schema<textarea className="schema-input" required rows="9" spellCheck="false" value={draft.output_schema} onChange={e => field('output_schema',e.target.value)} /></label>
        <p className="signal-help">Use a JSON object schema for each event’s custom fields. Editing the instruction or schema creates a new version.</p>
        <label className="signal-checkbox"><input type="checkbox" checked={draft.enabled} onChange={e => field('enabled',e.target.checked)} />Enabled</label>
        <button className="secondary-button" disabled={busy}>{busy ? 'Saving…' : 'Save Signal'}</button>
      </form></div> : <>
      <p className="signal-help">Showing up to 50 {tab} per page. Refresh to load worker updates.</p>
      {run && <p>Events for run {run} <button onClick={() => {setRun(''); setOffset(0);}}>Show all events</button></p>}
      {!loading && !error && !rows.length && <p className="empty-state">No {tab} here yet. Enabled Signals produce runs when the detection worker analyzes new conversations.</p>}
      {rows.map(row => <article className="signal-card" key={row.id}>
        <div className="signal-card-heading"><h2>{tab === 'runs' ? row.signal_name : row.summary}</h2><span className={`signal-status status-${row.status || row.severity}`}>{row.status || row.severity}</span></div>
        <p>{row.signal_name} · Version {row.signal_version} · Turn {row.turn_id}</p>
        {tab === 'runs' ? <><p>{row.user_message}</p><p>{row.event_count} events · {new Date(row.created_at).toLocaleString()}</p>{row.error && <p role="status">{row.error}</p>}
          <div className="signal-actions">{row.status === 'failed' && <button disabled={busy} onClick={() => retry(row.id)}>Retry analysis</button>}<button onClick={() => {setRun(row.id); setOffset(0); setTab('events');}}>View events</button><TraceLink url={row.laminar_url} /></div></>
          : <><p><strong>Evidence:</strong> {row.evidence}</p><details><summary>Custom fields and span citations</summary><pre>{JSON.stringify({payload: row.payload, supporting_span_ids: row.supporting_span_ids},null,2)}</pre></details><TraceLink url={row.laminar_url} /></>}
      </article>)}
      <div className="signal-actions"><button disabled={!offset || loading} onClick={() => setOffset(x => Math.max(0,x-50))}>Previous</button><span>Page {offset/50+1}</span><button disabled={rows.length < 50 || loading} onClick={() => setOffset(x => x+50)}>Next</button></div>
      </>}
  </main>;
}
