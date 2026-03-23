import Cocoa
import WebKit
import Photos

// ============================================================
// Fovea - Native macOS App Shell
//
// 1. Requests Photos access via PhotoKit (native dialog)
// 2. Exports photo metadata to JSON (lightweight, no thumbnails yet)
// 3. Generates thumbnails on-demand when Python requests them
// 4. Runs a thumbnail server alongside the Python backend
// ============================================================

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var serverProcess: Process?
    var setupProcess: Process?
    var thumbServer: ThumbnailServer?

    let foveaHome = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".fovea")
    var srcDir: String = ""
    let mainPort = 8080
    let setupPort = 9999
    let thumbPort = 9998  // Serves photo thumbnails on-demand

    func applicationDidFinishLaunching(_ notification: Notification) {
        srcDir = findSrcDir()

        let fm = FileManager.default
        try? fm.createDirectory(at: foveaHome, withIntermediateDirectories: true)
        try? fm.createDirectory(at: foveaHome.appendingPathComponent("data"), withIntermediateDirectories: true)
        try? fm.createDirectory(at: foveaHome.appendingPathComponent("thumbnails"), withIntermediateDirectories: true)

        // Create window
        let screenSize = NSScreen.main?.frame.size ?? NSSize(width: 1440, height: 900)
        let windowRect = NSRect(
            x: (screenSize.width - 1280) / 2,
            y: (screenSize.height - 820) / 2,
            width: 1280, height: 820
        )

        window = NSWindow(
            contentRect: windowRect,
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered, defer: false
        )
        window.title = "Fovea"
        window.minSize = NSSize(width: 900, height: 600)
        window.isReleasedWhenClosed = false
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden

        if let iconPath = Bundle.main.path(forResource: "fovea", ofType: "icns") {
            NSApp.applicationIconImage = NSImage(contentsOfFile: iconPath)
        }

        // WKWebView — disable native drag to prevent scroll issues
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.setValue(false, forKey: "drawsBackground")
        webView.allowsBackForwardNavigationGestures = false
        window.contentView?.addSubview(webView)

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        // Request Photos access → export metadata → launch
        requestPhotosAccess()
    }

    // ---- Photos Access ----

    func requestPhotosAccess() {
        PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
            DispatchQueue.main.async {
                switch status {
                case .authorized, .limited:
                    // Export metadata FIRST (synchronous on bg thread), THEN launch server
                    DispatchQueue.global(qos: .userInitiated).async {
                        self.doExportPhotoMetadata()
                        // Start thumbnail server (serves images on-demand)
                        self.thumbServer = ThumbnailServer(
                            port: self.thumbPort,
                            thumbDir: self.foveaHome.appendingPathComponent("thumbnails").path
                        )
                        self.thumbServer?.start()
                        DispatchQueue.main.async {
                            self.launchApp()
                        }
                    }
                default:
                    // No Photos access — still launch, library will show error
                    self.launchApp()
                }
            }
        }
    }

    func launchApp() {
        let fm = FileManager.default
        let venvPath = foveaHome.appendingPathComponent("venv")
        if fm.fileExists(atPath: venvPath.path) {
            startMainServer()
        } else {
            runFirstTimeSetup()
        }
    }

    // ---- Photo Metadata Export (lightweight, no thumbnails) ----

    func doExportPhotoMetadata() {
        let outputPath = foveaHome.appendingPathComponent("data/photos_library.json")
        let formatter = ISO8601DateFormatter()

        let fetchOptions = PHFetchOptions()
        fetchOptions.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
        let assets = PHAsset.fetchAssets(with: .image, options: fetchOptions)

        var photos: [[String: Any]] = []

        assets.enumerateObjects { (asset: PHAsset, idx: Int, _: UnsafeMutablePointer<ObjCBool>) in
            var info: [String: Any] = [
                "uuid": asset.localIdentifier,
                "width": asset.pixelWidth,
                "height": asset.pixelHeight,
                "is_favorite": asset.isFavorite,
                "is_hidden": asset.isHidden,
                // Thumbnail URL: on-demand via the thumbnail server
                "thumb_url": "http://127.0.0.1:\(self.thumbPort)/thumb?id=\(asset.localIdentifier.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")",
            ]

            if let date = asset.creationDate {
                info["date"] = formatter.string(from: date)
            }

            let resources = PHAssetResource.assetResources(for: asset)
            if let primary = resources.first {
                info["filename"] = primary.originalFilename
            }

            info["is_screenshot"] = asset.mediaSubtypes.contains(.photoScreenshot)
            info["is_live"] = asset.mediaSubtypes.contains(.photoLive)
            info["is_burst"] = asset.representsBurst

            photos.append(info)
        }

        // Albums
        var albums: [[String: Any]] = []
        let albumFetch = PHAssetCollection.fetchAssetCollections(with: .album, subtype: .any, options: nil)
        albumFetch.enumerateObjects { (col: PHAssetCollection, _: Int, _: UnsafeMutablePointer<ObjCBool>) in
            let count = PHAsset.fetchAssets(in: col, options: nil).count
            if count > 0 {
                albums.append([
                    "title": col.localizedTitle ?? "Untitled",
                    "uuid": col.localIdentifier,
                    "count": count,
                ])
            }
        }

        let smartTypes: [PHAssetCollectionSubtype] = [
            .smartAlbumFavorites, .smartAlbumScreenshots,
            .smartAlbumSelfPortraits, .smartAlbumRecentlyAdded,
        ]
        for subtype in smartTypes {
            let fetch = PHAssetCollection.fetchAssetCollections(with: .smartAlbum, subtype: subtype, options: nil)
            fetch.enumerateObjects { (col: PHAssetCollection, _: Int, _: UnsafeMutablePointer<ObjCBool>) in
                let c = PHAsset.fetchAssets(in: col, options: nil).count
                if c > 0 {
                    albums.append([
                        "title": col.localizedTitle ?? "Untitled",
                        "uuid": col.localIdentifier,
                        "count": c,
                        "is_smart": true,
                    ])
                }
            }
        }

        let output: [String: Any] = [
            "photo_count": photos.count,
            "album_count": albums.count,
            "photos": photos,
            "albums": albums,
            "thumb_port": thumbPort,
        ]

        if let jsonData = try? JSONSerialization.data(withJSONObject: output, options: []) {
            try? jsonData.write(to: outputPath)
        }
    }

    // ---- First-time Setup ----

    func runFirstTimeSetup() {
        let python = findPython()
        let setupScript = srcDir + "/setup_server.py"

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [setupScript, String(mainPort), String(setupPort)]
        process.currentDirectoryURL = URL(fileURLWithPath: srcDir)
        process.environment = buildEnv()

        let log = foveaHome.appendingPathComponent("fovea.log")
        let logHandle = FileHandle(forWritingAtPath: log.path) ?? {
            FileManager.default.createFile(atPath: log.path, contents: nil)
            return FileHandle(forWritingAtPath: log.path)!
        }()
        logHandle.seekToEndOfFile()
        process.standardOutput = logHandle
        process.standardError = logHandle
        setupProcess = process

        do { try process.run() } catch {
            showError("Failed to start setup: \(error)")
            return
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(self.setupPort)")!))
        }

        DispatchQueue.global(qos: .userInitiated).async {
            process.waitUntilExit()
            DispatchQueue.main.async { self.startMainServer() }
        }
    }

    // ---- Main Server ----

    func startMainServer() {
        let venvPython = foveaHome.appendingPathComponent("venv/bin/python3").path

        guard FileManager.default.fileExists(atPath: venvPython) else {
            showError("Python environment not found. Delete ~/.fovea and restart.")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: venvPython)
        process.arguments = [
            "-c",
            "import uvicorn; from main import app; uvicorn.run(app, host='127.0.0.1', port=\(mainPort), log_level='warning')"
        ]
        process.currentDirectoryURL = URL(fileURLWithPath: srcDir)
        process.environment = buildEnv()

        let log = foveaHome.appendingPathComponent("fovea.log")
        if let logHandle = FileHandle(forWritingAtPath: log.path) {
            logHandle.seekToEndOfFile()
            process.standardOutput = logHandle
            process.standardError = logHandle
        }

        serverProcess = process
        do { try process.run() } catch {
            showError("Failed to start server: \(error)")
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            self.waitForServer(port: self.mainPort, timeout: 15.0)
            DispatchQueue.main.async {
                self.webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(self.mainPort)")!))
            }
        }
    }

    // ---- Helpers ----

    func buildEnv() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["FOVEA_DATA_DIR"] = foveaHome.appendingPathComponent("data").path
        env["FOVEA_THUMBNAIL_DIR"] = foveaHome.appendingPathComponent("thumbnails").path
        return env
    }

    func findSrcDir() -> String {
        if let resourcePath = Bundle.main.resourcePath {
            let candidate = resourcePath + "/src"
            if FileManager.default.fileExists(atPath: candidate + "/main.py") {
                return candidate
            }
        }
        let cwd = FileManager.default.currentDirectoryPath
        return cwd
    }

    func findPython() -> String {
        for p in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"] {
            if FileManager.default.fileExists(atPath: p) { return p }
        }
        return "/usr/bin/python3"
    }

    func waitForServer(port: Int, timeout: Double = 15.0) {
        let start = Date()
        while Date().timeIntervalSince(start) < timeout {
            if let url = URL(string: "http://127.0.0.1:\(port)/"),
               let _ = try? Data(contentsOf: url) { return }
            Thread.sleep(forTimeInterval: 0.3)
        }
    }

    func showError(_ message: String) {
        DispatchQueue.main.async {
            let html = "<html><body style='font-family:-apple-system;display:flex;align-items:center;justify-content:center;height:100vh;background:#f5f5f7;'><div style='text-align:center;'><h2>Error</h2><p>\(message)</p></div></body></html>"
            self.webView.loadHTMLString(html, baseURL: nil)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        serverProcess?.terminate()
        setupProcess?.terminate()
        thumbServer?.stop()
    }
}


// ============================================================
// On-demand Thumbnail Server
//
// Serves photo thumbnails via PhotoKit when requested.
// Only generates a thumbnail when a specific photo is viewed.
// Caches to disk so each photo is only processed once.
// ============================================================

class ThumbnailServer {
    let port: Int
    let thumbDir: String
    var listener: Thread?
    var serverSocket: Int32 = -1

    init(port: Int, thumbDir: String) {
        self.port = port
        self.thumbDir = thumbDir
    }

    func start() {
        listener = Thread {
            self.run()
        }
        listener?.start()
    }

    func stop() {
        if serverSocket >= 0 { close(serverSocket) }
    }

    func run() {
        serverSocket = socket(AF_INET, SOCK_STREAM, 0)
        var opt: Int32 = 1
        setsockopt(serverSocket, SOL_SOCKET, SO_REUSEADDR, &opt, socklen_t(MemoryLayout<Int32>.size))

        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = UInt16(port).bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")

        withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                bind(serverSocket, sa, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }

        listen(serverSocket, 32)

        while true {
            let client = accept(serverSocket, nil, nil)
            if client < 0 { break }

            DispatchQueue.global(qos: .utility).async {
                self.handleClient(client)
            }
        }
    }

    func handleClient(_ client: Int32) {
        var buffer = [UInt8](repeating: 0, count: 4096)
        let n = recv(client, &buffer, buffer.count, 0)
        guard n > 0 else { close(client); return }

        let request = String(bytes: buffer[0..<n], encoding: .utf8) ?? ""

        // Parse: GET /thumb?id=XXXXX HTTP/1.1
        if let idRange = request.range(of: "id="),
           let endRange = request.range(of: " HTTP", range: idRange.upperBound..<request.endIndex) {
            let rawId = String(request[idRange.upperBound..<endRange.lowerBound])
            let photoId = rawId.removingPercentEncoding ?? rawId

            if let jpegData = getThumbnail(for: photoId) {
                let header = "HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: \(jpegData.count)\r\nAccess-Control-Allow-Origin: *\r\nCache-Control: max-age=86400\r\n\r\n"
                send(client, header, header.utf8.count, 0)
                jpegData.withUnsafeBytes { ptr in
                    send(client, ptr.baseAddress, jpegData.count, 0)
                }
            } else {
                let resp = "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
                send(client, resp, resp.utf8.count, 0)
            }
        } else {
            let resp = "HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"
            send(client, resp, resp.utf8.count, 0)
        }

        close(client)
    }

    func getThumbnail(for localIdentifier: String) -> Data? {
        // Check cache first
        let cacheKey = localIdentifier.replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: ":", with: "_")
        let cachePath = thumbDir + "/" + cacheKey + ".jpg"

        if FileManager.default.fileExists(atPath: cachePath) {
            return try? Data(contentsOf: URL(fileURLWithPath: cachePath))
        }

        // Fetch from PhotoKit
        let fetchResult = PHAsset.fetchAssets(withLocalIdentifiers: [localIdentifier], options: nil)
        guard let asset = fetchResult.firstObject else { return nil }

        let options = PHImageRequestOptions()
        options.isSynchronous = true
        options.deliveryMode = .fastFormat
        options.resizeMode = .fast
        options.isNetworkAccessAllowed = true  // Allow downloading from iCloud

        var resultData: Data?
        let targetSize = CGSize(width: 400, height: 400)

        PHImageManager.default().requestImage(
            for: asset, targetSize: targetSize,
            contentMode: .aspectFill, options: options
        ) { image, _ in
            if let image = image {
                let rect = NSRect(origin: .zero, size: image.size)
                guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return }
                let rep = NSBitmapImageRep(cgImage: cgImage)
                if let jpeg = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.75]) {
                    // Cache to disk
                    try? jpeg.write(to: URL(fileURLWithPath: cachePath))
                    resultData = jpeg
                }
            }
        }

        return resultData
    }
}


// ---- Entry Point ----
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
