import { useState, type ChangeEvent, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/store';
import { ACCEPT, checkFile, formatBytes } from './fileRules';
import ProgressBar from './ProgressBar';
import { isUploadActive, uploadCancelled, uploadRequested, uploadReset, type UploadStage } from './uploadSlice';

const STAGE_LABELS: Record<UploadStage, string> = {
  idle: '',
  requesting: 'Preparing upload…',
  uploading: 'Uploading',
  completing: 'Finishing up…',
  processing: 'Uploaded. Encoding into 480p, 720p and 1080p… You can leave this page.',
  ready: 'Your video is ready.',
  failed: 'Failed',
  cancelled: 'Upload cancelled.',
};

export default function UploadPage() {
  const dispatch = useAppDispatch();
  const upload = useAppSelector((s) => s.upload);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const chosen = e.target.files?.[0] ?? null;
    setFile(chosen);
    const check = chosen ? checkFile(chosen) : null;
    setFileError(check && !check.ok ? check.error : null);
    if (chosen && !title) setTitle(chosen.name.replace(/\.[^.]+$/, ''));
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const check = checkFile(file);
    if (!check.ok) {
      setFileError(check.error);
      return;
    }
    dispatch(uploadRequested({ file, contentType: check.contentType, title: title.trim(), description }));
  };

  const startOver = () => {
    dispatch(uploadReset());
    setFile(null);
    setTitle('');
    setDescription('');
  };

  if (upload.stage !== 'idle') {
    const active = isUploadActive(upload.stage);
    return (
      <section className="card upload-status" aria-live="polite">
        <h1>{upload.fileName}</h1>
        {active && <ProgressBar value={upload.progress} label="Upload progress" />}
        {upload.stage === 'processing' && <div className="progress-indeterminate" aria-hidden="true" />}
        <p className={upload.stage === 'failed' ? 'error' : 'muted'}>
          {STAGE_LABELS[upload.stage]}
          {upload.error ? `: ${upload.error}` : ''}
        </p>
        <div className="row">
          {active ? (
            <button className="secondary" onClick={() => dispatch(uploadCancelled())}>
              Cancel upload
            </button>
          ) : (
            <>
              {upload.stage === 'ready' && upload.videoId && (
                <Link to={`/watch/${upload.videoId}`} className="button-link">
                  Watch now
                </Link>
              )}
              <button className={upload.stage === 'ready' ? 'secondary' : undefined} onClick={startOver}>
                Upload another
              </button>
              <Link to="/my" className="button-link secondary">
                Go to my videos
              </Link>
            </>
          )}
        </div>
      </section>
    );
  }

  return (
    <form className="card upload-form" onSubmit={onSubmit}>
      <h1>Upload a video</h1>
      <label>
        Video file
        <input type="file" accept={ACCEPT} required onChange={onFileChange} />
      </label>
      {file && !fileError && (
        <p className="muted small">
          {file.name} · {formatBytes(file.size)}
        </p>
      )}
      {fileError && (
        <p className="error" role="alert">
          {fileError}
        </p>
      )}
      <label>
        Title
        <input required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label>
        Description
        <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <p className="muted small">MP4, MOV, MKV or WebM, up to 5 GB.</p>
      <button type="submit" disabled={!file || !!fileError || !title.trim()}>
        Upload
      </button>
    </form>
  );
}
