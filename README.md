# convert-to-h265

This is a simple script to convert all videos in a directory to h265 using ffmpeg.

## Flowchart for file discovery

```mermaid
graph TD
    A(Start) --> B[Recursively get all files in directory]
    B --> C[Loop through files]
    C --> D[Check whether file is in database]
    D --No--> E[ffprobe file]
    D --Yes--> O
    E --> F[Loop through streams]
    F --> G[Get stream type]
    G --Video--> H[Incrememt Video Stream count]
    G --Audio--> I[Incrememt Audio Stream count]
    G --Subs--> J[Incrememt Subs Stream count]
    H --> K[Check if Video Stream is h265]
    K --Yes--> L[Set Don't Convert Flag]
    L --> M[End of loop]
    I --> M
    J --> M
    M --> F
    M --> N(Add data to database)
    N --> O[End of loop]
    O --> C
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

## Flowchart for file manipulation
```mermaid
graph TD
    A(Start) --> B[Get path to convert]
    B --> C[Get __filename__ and __ext__]
    C --> D[Create new temporary input path\n/Conversions/__filename__.__ext__]
    D --> E[Create new temporary output path\n/Conversions/__filename__.conv.__ext__]
    E --> F[Copy file to temporary input path]
    F --> G[Run ffmpeg command to convert file\nfrom temporary input path\nto temporary output path]
    G --> H[Copy file from temporary input path\nto backup path]
    H --> I[Copy file from temporary output path\nto original path]
    I --> J[Delete temporary input path]
    J --> K[Delete temporary output path]
    K --> L(End)
```
