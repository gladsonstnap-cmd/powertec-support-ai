"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { apiJson } from "@/lib/api";
import type { KnowledgeChunk, KnowledgeDocument, KnowledgeSearchResult } from "@/types/knowledge";

function KnowledgeContent() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([]);
  const [results, setResults] = useState<KnowledgeSearchResult[]>([]);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("todos os caixas sem conexao");
  const [title, setTitle] = useState("");
  const [product, setProduct] = useState("PDV PowerVarejo");
  const [content, setContent] = useState("");

  function refresh() {
    apiJson<KnowledgeDocument[]>("/knowledge/documents")
      .then(setDocuments)
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Nao foi possivel carregar documentos."));
  }

  useEffect(refresh, []);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      await apiJson<KnowledgeDocument>("/knowledge/documents", {
        method: "POST",
        body: JSON.stringify({
          title,
          filename: `${title.toLowerCase().replaceAll(" ", "-") || "documento"}.md`,
          mime_type: "text/markdown",
          content_base64: btoa(unescape(encodeURIComponent(content))),
          product,
          category: "demo",
          version: "demo-1.0",
          approve: false
        })
      });
      setTitle("");
      setContent("");
      refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Upload nao concluido.");
    }
  }

  async function review(documentId: string, approved: boolean) {
    await apiJson<KnowledgeDocument>(`/knowledge/documents/${documentId}/approval`, {
      method: "POST",
      body: JSON.stringify({ approved })
    });
    refresh();
  }

  async function search() {
    setResults(await apiJson<KnowledgeSearchResult[]>("/knowledge/search", {
      method: "POST",
      body: JSON.stringify({ query, product: product || undefined })
    }));
  }

  async function showChunks(documentId: string) {
    setChunks(await apiJson<KnowledgeChunk[]>(`/knowledge/documents/${documentId}/chunks`));
  }

  return (
    <div className="text-ink">
      <header className="mb-5">
        <div>
          <p className="mt-1 text-sm text-slate-600">Documentos aprovados, indexados e pesquisaveis por tenant.</p>
        </div>
      </header>

      {error ? <p className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}

      <section className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <form onSubmit={upload} className="rounded border border-slate-200 bg-white p-4">
          <h2 className="font-semibold">Enviar documento</h2>
          <input className="mt-3 w-full rounded border border-slate-300 px-3 py-2 text-sm" placeholder="Titulo" value={title} onChange={(event) => setTitle(event.target.value)} required />
          <input className="mt-3 w-full rounded border border-slate-300 px-3 py-2 text-sm" placeholder="Produto" value={product} onChange={(event) => setProduct(event.target.value)} />
          <textarea className="mt-3 h-40 w-full rounded border border-slate-300 px-3 py-2 text-sm" placeholder="Conteudo Markdown/TXT" value={content} onChange={(event) => setContent(event.target.value)} required />
          <button className="mt-3 rounded bg-brand px-4 py-2 text-sm text-white" type="submit">Enviar</button>
        </form>

        <div className="rounded border border-slate-200 bg-white p-4">
          <h2 className="font-semibold">Pesquisar</h2>
          <div className="mt-3 flex gap-2">
            <input className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm" value={query} onChange={(event) => setQuery(event.target.value)} />
            <button className="rounded bg-brand px-4 py-2 text-sm text-white" onClick={search}>Buscar</button>
          </div>
          <div className="mt-4 space-y-2">
            {results.map((result) => (
              <div key={result.reference} className="rounded border border-slate-200 p-3 text-sm">
                <div className="font-medium">{result.title} <span className="text-slate-500">({Math.round(result.score * 100)}%)</span></div>
                <p className="mt-1 text-slate-600">{result.excerpt}</p>
                <p className="mt-1 text-xs text-slate-500">{result.product ?? "-"} / {result.version ?? "-"} / {result.reference}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mt-5 overflow-hidden rounded border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-100">
            <tr><th className="px-4 py-3">Titulo</th><th>Produto</th><th>Status</th><th>Versao</th><th>Acoes</th></tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr key={document.id} className="border-t border-slate-200">
                <td className="px-4 py-3 font-medium">{document.title}</td>
                <td>{document.product ?? "-"}</td>
                <td>{document.status}</td>
                <td>{document.version ?? "-"}</td>
                <td className="space-x-2 py-2">
                  <button className="rounded border border-slate-300 px-2 py-1" onClick={() => showChunks(document.id)}>Chunks</button>
                  <button className="rounded border border-emerald-300 px-2 py-1" onClick={() => review(document.id, true)}>Aprovar</button>
                  <button className="rounded border border-red-300 px-2 py-1" onClick={() => review(document.id, false)}>Reprovar</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {chunks.length > 0 ? (
        <section className="mt-5 rounded border border-slate-200 bg-white p-4">
          <h2 className="font-semibold">Chunks</h2>
          <div className="mt-3 space-y-2">
            {chunks.map((chunk) => <pre key={chunk.id} className="whitespace-pre-wrap rounded bg-slate-100 p-3 text-xs">{chunk.content}</pre>)}
          </div>
        </section>
      ) : null}
    </div>
  );
}

export default function KnowledgePage() {
  return <AppShell title="Base de conhecimento"><KnowledgeContent /></AppShell>;
}
