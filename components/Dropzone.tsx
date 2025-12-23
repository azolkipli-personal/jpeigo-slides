
import React, { useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import styles from './Dropzone.module.css';

interface DropzoneProps {
    onFileAccepted: (file: File) => void;
    isLoading: boolean;
}

const Dropzone: React.FC<DropzoneProps> = ({ onFileAccepted, isLoading }) => {
    const onDrop = useCallback((acceptedFiles: File[]) => {
        if (acceptedFiles.length > 0) {
            onFileAccepted(acceptedFiles[0]);
        }
    }, [onFileAccepted]);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: {
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx']
        },
        multiple: false,
        disabled: isLoading
    });

    return (
        <div {...getRootProps()} className={`${styles.dropzone} ${isDragActive ? styles.active : ''} ${isLoading ? styles.loading : ''}`}>
            <input {...getInputProps()} />
            {isLoading ? (
                <div className={styles.content}>
                    <div className={styles.spinner}></div>
                    <p>Converting your presentation...</p>
                </div>
            ) : (
                <div className={styles.content}>
                    <span className={styles.icon}>📂</span>
                    <p className={styles.text}>
                        {isDragActive ? "Drop the PPTX here..." : "Drag & drop your PowerPoint file here, or click to select"}
                    </p>
                </div>
            )}
        </div>
    );
};

export default Dropzone;
