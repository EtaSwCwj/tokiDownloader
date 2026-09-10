// Isolated subprocess crash fixture. Only the caller-created temporary root.
import { downloadEpisodeImages } from '../../downloader_image_resume.js';
import { existingImageFileIsValid, runDownloadTasks, writeImageBufferAtomically } from '../../down.js';
await downloadEpisodeImages(process.argv[2], {sourceId:'/manhwa/1/2',folderName:'000002 작품 2화'},
    [1,2].map(id=>({src:`https://images.test/${id}.jpg`,extension:'.jpg'})), {
        validateFile:existingImageFileIsValid,runTasks:runDownloadTasks,concurrency:1,
        saveImage:async(directory,fileName)=>{
            await writeImageBufferAtomically(directory,fileName,Buffer.from([255,216,255,224,1,255,217]));
            process.exit(77);
        },
    });
