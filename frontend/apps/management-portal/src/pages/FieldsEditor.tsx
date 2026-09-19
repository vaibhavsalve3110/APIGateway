import { emptyField, type ApiField } from "@apigw/ui";

const TYPES = ["string", "integer", "number", "boolean", "object", "array"];

/** Editable name / type / required / example / description rows for parameters, headers and body fields. */
export function FieldsEditor({ fields, onChange, readOnly, addLabel = "+ Add row", namePlaceholder = "name" }: {
  fields: ApiField[];
  onChange: (next: ApiField[]) => void;
  readOnly?: boolean;
  addLabel?: string;
  namePlaceholder?: string;
}) {
  const update = (i: number, patch: Partial<ApiField>) => onChange(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  const types = (current: string) => (TYPES.includes(current) ? TYPES : [...TYPES, current]);

  return (
    <div className="stack" style={{ gap: 8 }}>
      {fields.length > 0 ? (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: "24%" }}>Name</th><th style={{ width: "13%" }}>Type</th><th style={{ width: 70 }}>Required</th>
                <th style={{ width: "20%" }}>Example</th><th>Description</th>{readOnly ? null : <th style={{ width: 40 }} />}
              </tr>
            </thead>
            <tbody>
              {fields.map((f, i) => (
                <tr key={i}>
                  <td><input className="input cell-input mono" aria-label="Name" placeholder={namePlaceholder} value={f.name} disabled={readOnly}
                    onChange={(e) => update(i, { name: e.target.value })} /></td>
                  <td>
                    <select className="select cell-input" aria-label="Type" value={f.type} disabled={readOnly} onChange={(e) => update(i, { type: e.target.value })}>
                      {types(f.type).map((t) => <option key={t}>{t}</option>)}
                    </select>
                  </td>
                  <td style={{ textAlign: "center" }}>
                    <input type="checkbox" aria-label="Required" checked={f.required} disabled={readOnly} onChange={(e) => update(i, { required: e.target.checked })} />
                  </td>
                  <td><input className="input cell-input mono" aria-label="Example" value={f.example ?? ""} disabled={readOnly}
                    onChange={(e) => update(i, { example: e.target.value || null })} /></td>
                  <td><input className="input cell-input" aria-label="Description" value={f.description ?? ""} disabled={readOnly}
                    onChange={(e) => update(i, { description: e.target.value || null })} /></td>
                  {readOnly ? null : (
                    <td><button type="button" className="btn btn-sm" aria-label="Remove row" title="Remove"
                      onClick={() => onChange(fields.filter((_, j) => j !== i))}>✕</button></td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {readOnly ? null : (
        <div><button type="button" className="btn btn-sm" onClick={() => onChange([...fields, emptyField()])}>{addLabel}</button></div>
      )}
    </div>
  );
}
