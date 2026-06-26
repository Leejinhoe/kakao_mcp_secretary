import Foundation
import Vision

if CommandLine.arguments.count < 2 {
    FileHandle.standardError.write(Data("Usage: macos_vision_ocr.swift <image_path> [language_csv]\n".utf8))
    exit(2)
}

let imagePath = CommandLine.arguments[1]
let languageCSV = CommandLine.arguments.count >= 3 ? CommandLine.arguments[2] : "ko-KR,en-US"
let recognitionLanguages = languageCSV
    .split(separator: ",")
    .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
    .filter { !$0.isEmpty }

guard let imageData = FileManager.default.contents(atPath: imagePath) else {
    FileHandle.standardError.write(Data("Cannot load image: \(imagePath)\n".utf8))
    exit(3)
}

func supportedLanguages(for revision: Int, level: VNRequestTextRecognitionLevel) -> [String] {
    if #available(macOS 13.0, *) {
        return (try? VNRecognizeTextRequest.supportedRecognitionLanguages(for: level, revision: revision)) ?? []
    }
    return []
}

func performOCR(with languages: [String], revision: Int, level: VNRequestTextRecognitionLevel) throws -> [String] {
    let request = VNRecognizeTextRequest()
    request.revision = revision
    request.recognitionLevel = level
    request.usesLanguageCorrection = true
    request.usesCPUOnly = true

    let supported = supportedLanguages(for: revision, level: level)
    let filteredLanguages = supported.isEmpty ? languages : languages.filter { supported.contains($0) }
    if !filteredLanguages.isEmpty {
        request.recognitionLanguages = filteredLanguages
    }

    let handler = VNImageRequestHandler(data: imageData, options: [:])
    try handler.perform([request])
    return (request.results ?? [])
        .compactMap { $0.topCandidates(1).first?.string }
        .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
}

let revisionCandidates = [
    VNRecognizeTextRequestRevision3,
    VNRecognizeTextRequestRevision2,
    VNRecognizeTextRequestRevision1
]

func performWithRevisionFallback(languages: [String]) throws -> [String] {
    var lastError: Error?
    for level in [VNRequestTextRecognitionLevel.accurate, VNRequestTextRecognitionLevel.fast] {
        for revision in revisionCandidates {
            do {
                return try performOCR(with: languages, revision: revision, level: level)
            } catch {
                lastError = error
            }
        }
    }
    throw lastError ?? NSError(domain: "TalkGuardOCR", code: 1)
}

do {
    var lines = try performWithRevisionFallback(languages: recognitionLanguages)
    if lines.isEmpty && !recognitionLanguages.isEmpty {
        lines = try performWithRevisionFallback(languages: [])
    }
    print(lines.joined(separator: "\n"))
} catch {
    do {
        let lines = try performWithRevisionFallback(languages: [])
        print(lines.joined(separator: "\n"))
    } catch {
        FileHandle.standardError.write(Data("Vision OCR failed: \(error.localizedDescription)\n".utf8))
        exit(4)
    }
}
