# convert-to-h265

This is a simple script to convert all videos in a directory to h265 using ffmpeg.

## Flowchart for file discovery

```mermaid
graph TD
    A(Start) --> B[Recursively get all files in directory]
    B --> C[Loop through files]
    C --> D[Check whether file is in database]
    D --No--> E[ffprobe file]
    D --Yes--> N
    E --> F[Loop through streams]
    F --> G[Get stream type]
    G --Video--> H[Incrememt Video Stream count]
    G --Audio--> I[Incrememt Audio Stream count]
    G --Subs--> J[Incrememt Subs Stream count]
    H --> K[Check if Video Stream is h265]
    K --Yes--> L[Set Don't Convert Flag]
    L --> M[Add data to database]
    I --> M
    J --> M
    M --> N(End of loop)
    N --> C
```

## Flowchart for conversion

```mermaid
graph TD
    A(Start) --> B[Get all files in database]
    B --> C[Filter out files with\nDon't Convert Flag set to true]
    C --> D[Loop through remaining files]
    D --> E[Check if file has\nonly one Video Stream and\nonly one Audio Stream]
    E --Yes--> F[Convert file]
    F --> G[Set Don't Convert Flag to true\nand update database]
    E --No--> H(End of loop)
    G --> H
    H --> D
```
