export function UploadProgress({ label }: { label: string }) {
  return label ? <p role="status" aria-live="polite" className="px-4 py-2 text-sm text-blue-700 bg-blue-50">{label}</p> : null;
}
