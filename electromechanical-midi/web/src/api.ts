/** Klient REST - lista plikow, metadane, porty. */

import type { FileMetadata, MidiFileEntry, PortsResponse } from './types'

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url)

  if (!response.ok) {
    let detail = `HTTP ${response.status}`

    try {
      const body = (await response.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      /* odpowiedz bez JSON - zostaje sam status */
    }

    throw new Error(detail)
  }

  return (await response.json()) as T
}

export async function fetchFiles(): Promise<MidiFileEntry[]> {
  const data = await getJson<{ files: MidiFileEntry[] }>('/api/files')

  return data.files
}

export async function fetchMetadata(name: string): Promise<FileMetadata> {
  return getJson<FileMetadata>(`/api/files/${encodeURIComponent(name)}`)
}

export async function fetchPorts(): Promise<PortsResponse> {
  return getJson<PortsResponse>('/api/ports')
}
