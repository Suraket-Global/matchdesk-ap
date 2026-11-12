import { useId, useState, type ReactNode } from "react";
import { UploadCloud } from "lucide-react";

/** Drag-and-drop zone with a real file input inside, so keyboard and screen-reader users choose
 * files the ordinary way. Calls `onFiles` with every dropped or chosen file. */
export function FileDropzone(props: {
  onFiles: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  title: string;
  hint?: ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  const [over, setOver] = useState(false);
  const id = useId();
  return (
    <div
      className={`dropzone ${over ? "over" : ""} ${props.className ?? ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!props.disabled) props.onFiles(Array.from(e.dataTransfer.files));
      }}
    >
      <span className="dz-icon" aria-hidden="true">
        <UploadCloud size={22} />
      </span>
      <h2>{props.title}</h2>
      {props.hint && <p>{props.hint}</p>}
      <label htmlFor={id} className="btn primary" style={{ marginTop: 8 }}>
        Choose files
      </label>
      <input
        id={id}
        type="file"
        className="sr-only"
        accept={props.accept}
        multiple={props.multiple ?? true}
        disabled={props.disabled}
        onChange={(e) => {
          props.onFiles(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
    </div>
  );
}
