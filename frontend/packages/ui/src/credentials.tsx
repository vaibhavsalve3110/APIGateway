import { useState } from "react";

import { Modal, CopyButton } from "./components";
import { CodeBlock } from "./docsView";
import type { IssuedCredentials } from "./types";

/**
 * Shows credentials issued to an organization once: the private signature key exists nowhere else, so the
 * dialog cannot be dismissed until the operator confirms they have handed it over.
 */
export function IssuedCredentialsModal({ issued, onClose }: { issued: IssuedCredentials; onClose: () => void }) {
  const [stored, setStored] = useState(false);
  const { partner, privateKeyPem, publicKeyPem, ipvSalt } = issued;

  const title = privateKeyPem && ipvSalt
    ? `Credentials for ${partner?.name ?? "this organization"}`
    : privateKeyPem ? "New signature key pair" : "New IPV salt";

  const download = () => {
    const parts = [
      `# API Gateway — credentials for ${partner?.name ?? "organization"}${partner ? ` (${partner.code})` : ""}`,
      `# Issued: ${new Date().toISOString()}`,
      partner?.signatureFingerprint ? `# Signature fingerprint: ${partner.signatureFingerprint}` : "",
      "",
      privateKeyPem ? `# Private signature key (${partner?.signatureAlgorithm ?? "RSA"}) — keep secret\n${privateKeyPem}` : "",
      publicKeyPem ? `# Public signature key — held by the platform\n${publicKeyPem}` : "",
      ipvSalt ? `# IPV salt\n${ipvSalt}\n` : "",
    ].filter(Boolean).join("\n");
    const url = URL.createObjectURL(new Blob([parts], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${partner?.code ?? "organization"}-credentials.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Modal
      title={title}
      width={700}
      onClose={() => stored && onClose()}
      footer={<>
        <label className="row grow" style={{ gap: 8, fontSize: 12.5 }}>
          <input type="checkbox" checked={stored} onChange={(e) => setStored(e.target.checked)} />
          I have handed these to the organization securely
        </label>
        <button className="btn" onClick={download}>Download .txt</button>
        <button className="btn btn-primary" disabled={!stored} onClick={onClose}>Done</button>
      </>}
    >
      <div className={privateKeyPem ? "banner banner-warn" : "banner banner-info"} style={{ fontSize: 12.5 }}>
        {issued.notice ?? "Shown once."}
      </div>

      {ipvSalt ? (
        <section className="stack" style={{ gap: 6 }}>
          <span className="label">IPV salt</span>
          <div className="secret">{ipvSalt}</div>
          <div className="row"><CopyButton value={ipvSalt} label="Copy salt" /></div>
        </section>
      ) : null}

      {privateKeyPem ? (
        <section className="stack" style={{ gap: 6 }}>
          <div className="row" style={{ gap: 8 }}>
            <span className="label grow">Private signature key · {partner?.signatureAlgorithm ?? "RSA-2048/SHA-256"}</span>
            <CopyButton value={privateKeyPem} label="Copy private key" />
          </div>
          <CodeBlock code={privateKeyPem} maxHeight={200} />
          {partner?.signatureFingerprint ? (
            <span className="muted mono" style={{ fontSize: 11 }}>{partner.signatureFingerprint}</span>
          ) : null}
        </section>
      ) : null}

      {publicKeyPem ? (
        <section className="stack" style={{ gap: 6 }}>
          <div className="row" style={{ gap: 8 }}>
            <span className="label grow">Public signature key (held by the platform)</span>
            <CopyButton value={publicKeyPem} label="Copy public key" />
          </div>
          <CodeBlock code={publicKeyPem} maxHeight={150} />
        </section>
      ) : null}
    </Modal>
  );
}
