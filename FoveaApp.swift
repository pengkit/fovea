import Cocoa
import WebKit
import Photos

// ============================================================
// Fovea - Native macOS App Shell (Minimal & Robust)
//
// Swift only does: window + webview + photos permission + metadata export
// Python server is launched as a fully detached background process
// ============================================================

func logMsg(_ msg: String) {
    let home = FileManager.default.homeDirectoryForCurrentUser
    let logFile = home.appendingPathComponent(".fovea/swift.log")
    let ts = ISO8601DateFormatter().string(from: Date())
    let line = "[\(ts)] \(msg)\n"
    if let handle = FileHandle(forWritingAtPath: logFile.path) {
        handle.seekToEndOfFile()
        handle.write(line.data(using: .utf8)!)
        handle.closeFile()
    } else {
        FileManager.default.createFile(atPath: logFile.path, contents: line.data(using: .utf8))
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var thumbServer: ThumbnailServer?

    let foveaHome = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".fovea")
    var srcDir: String = ""
    let mainPort = 8080
    let thumbPort = 9998

    func applicationDidFinishLaunching(_ notification: Notification) {
        logMsg("App starting")
        srcDir = findSrcDir()
        logMsg("srcDir: \(srcDir)")

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

        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.setValue(false, forKey: "drawsBackground")
        webView.allowsBackForwardNavigationGestures = false
        window.contentView?.addSubview(webView)

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        // Show loading with progress steps
        let bg = isDarkMode() ? "#0f1117" : "#f5f5f7"
        let fg = isDarkMode() ? "#e8eaed" : "#1d1d1f"
        let fg2 = isDarkMode() ? "#565a6e" : "#9ca3af"
        let accent = "#6366f1"
        let loadingHtml = """
        <html><head><style>
        @keyframes spin { to { transform: rotate(360deg); } }
        .spinner { width:28px;height:28px;border:3px solid \(fg2);border-top-color:\(accent);border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 16px; }
        </style></head>
        <body style='font-family:-apple-system;display:flex;align-items:center;justify-content:center;height:100vh;background:\(bg);color:\(fg);'>
        <div style='text-align:center;'>
          <div class='spinner'></div>
          <p id='step' style='font-size:14px;font-weight:500;'>Starting...</p>
          <p id='detail' style='font-size:11px;color:\(fg2);margin-top:6px;'></p>
        </div></body></html>
        """
        webView.loadHTMLString(loadingHtml, baseURL: nil)
        logMsg("Window created, loading shown")

        // Everything else happens in background
        DispatchQueue.global(qos: .userInitiated).async {
            self.bootstrapApp()
        }
    }

    // ---- Bootstrap (runs on background thread) ----

    func updateStep(_ step: String, detail: String = "") {
        let safeStep = step.replacingOccurrences(of: "'", with: "\\'")
        let safeDetail = detail.replacingOccurrences(of: "'", with: "\\'")
        DispatchQueue.main.async {
            self.webView.evaluateJavaScript(
                "document.getElementById('step').textContent='\(safeStep)';document.getElementById('detail').textContent='\(safeDetail)';",
                completionHandler: nil
            )
        }
    }

    func bootstrapApp() {
        // 1. Request Photos access
        updateStep("Requesting Photos access...")
        logMsg("Requesting Photos access")
        let semaphore = DispatchSemaphore(value: 0)
        var photosAuthorized = false

        PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
            photosAuthorized = (status == .authorized || status == .limited)
            logMsg("Photos access: \(status.rawValue) authorized=\(photosAuthorized)")
            semaphore.signal()
        }
        semaphore.wait()

        // 2. Export photo metadata if authorized
        if photosAuthorized {
            updateStep("Reading Photos library...", detail: "This may take a moment")
            logMsg("Exporting photo metadata")
            doExportPhotoMetadata()
            logMsg("Photo metadata exported")

            updateStep("Starting thumbnail service...")
            thumbServer = ThumbnailServer(
                port: thumbPort,
                thumbDir: foveaHome.appendingPathComponent("thumbnails").path
            )
            thumbServer?.start()
            logMsg("Thumbnail server started on port \(thumbPort)")
        }

        // 3. Check if venv exists
        let venvPython = foveaHome.appendingPathComponent("venv/bin/python3").path
        if !FileManager.default.fileExists(atPath: venvPython) {
            logMsg("No venv found, running first-time setup")
            runFirstTimeSetup()
            return
        }

        // 4. Start Python server
        updateStep("Starting server...")
        logMsg("Starting Python server")
        startPythonServer()

        // 5. Wait for server
        updateStep("Almost ready...", detail: "Waiting for server")
        logMsg("Waiting for server on port \(mainPort)")
        let ready = waitForServer(port: mainPort, timeout: 25.0)
        logMsg("Server ready: \(ready)")

        // 6. Load the page
        DispatchQueue.main.async {
            if ready {
                logMsg("Loading main page")
                self.webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(self.mainPort)")!))
            } else {
                logMsg("Server timeout, showing error")
                let html = "<html><body style='font-family:-apple-system;display:flex;align-items:center;justify-content:center;height:100vh;background:#f5f5f7;'><div style='text-align:center;'><h2>Error</h2><p>Server failed to start. Check ~/.fovea/swift.log</p></div></body></html>"
                self.webView.loadHTMLString(html, baseURL: nil)
            }
        }
    }

    // ---- Start Python server as detached process ----

    func startPythonServer() {
        let logPath = foveaHome.appendingPathComponent("fovea.log").path
        // Launch via bash, nohup + & to fully detach from this process
        let script = """
        lsof -ti:\(mainPort) | xargs kill -9 2>/dev/null
        sleep 0.3
        source "\(foveaHome.path)/venv/bin/activate"
        cd "\(srcDir)"
        export FOVEA_DATA_DIR="\(foveaHome.path)/data"
        export FOVEA_THUMBNAIL_DIR="\(foveaHome.path)/thumbnails"
        export PYTHONDONTWRITEBYTECODE=1
        nohup python3 -c "import uvicorn; from main import app; uvicorn.run(app, host='127.0.0.1', port=\(mainPort), log_level='warning')" >> "\(logPath)" 2>&1 &
        """

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = ["-c", script]
        // Don't store reference — fire and forget
        do { try process.run() } catch {
            logMsg("Failed to start Python server: \(error)")
        }
        logMsg("Python server launch command sent")
    }

    // ---- First-time Setup ----

    func runFirstTimeSetup() {
        let python = findPython()
        let setupScript = srcDir + "/setup_server.py"
        let setupPort = 9999

        logMsg("Running setup: \(python) \(setupScript)")

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [setupScript, String(mainPort), String(setupPort)]
        process.currentDirectoryURL = URL(fileURLWithPath: srcDir)

        var env = ProcessInfo.processInfo.environment
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["FOVEA_DATA_DIR"] = foveaHome.appendingPathComponent("data").path
        env["FOVEA_THUMBNAIL_DIR"] = foveaHome.appendingPathComponent("thumbnails").path
        process.environment = env

        let log = foveaHome.appendingPathComponent("fovea.log")
        FileManager.default.createFile(atPath: log.path, contents: nil)
        if let logHandle = FileHandle(forWritingAtPath: log.path) {
            process.standardOutput = logHandle
            process.standardError = logHandle
        }

        do { try process.run() } catch {
            logMsg("Setup failed: \(error)")
            DispatchQueue.main.async {
                let html = "<html><body style='font-family:-apple-system;display:flex;align-items:center;justify-content:center;height:100vh;'><div><h2>Setup Error</h2><p>\(error)</p></div></body></html>"
                self.webView.loadHTMLString(html, baseURL: nil)
            }
            return
        }

        // Show setup UI
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(setupPort)")!))
        }

        // Wait for setup to finish, then start main server
        process.waitUntilExit()
        logMsg("Setup finished with exit code \(process.terminationStatus)")
        startPythonServer()

        let ready = waitForServer(port: mainPort, timeout: 25.0)
        DispatchQueue.main.async {
            if ready {
                self.webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(self.mainPort)")!))
            }
        }
    }

    // ---- Photo Metadata Export ----

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

    // ---- Helpers ----

    func isDarkMode() -> Bool {
        if let appearance = NSApp.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) {
            return appearance == .darkAqua
        }
        return false
    }

    func findSrcDir() -> String {
        if let resourcePath = Bundle.main.resourcePath {
            let candidate = resourcePath + "/src"
            if FileManager.default.fileExists(atPath: candidate + "/main.py") {
                return candidate
            }
        }
        return FileManager.default.currentDirectoryPath
    }

    func findPython() -> String {
        for p in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"] {
            if FileManager.default.fileExists(atPath: p) { return p }
        }
        return "/usr/bin/python3"
    }

    func waitForServer(port: Int, timeout: Double = 15.0) -> Bool {
        let start = Date()
        while Date().timeIntervalSince(start) < timeout {
            if let url = URL(string: "http://127.0.0.1:\(port)/"),
               let _ = try? Data(contentsOf: url) { return true }
            Thread.sleep(forTimeInterval: 0.3)
        }
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationWillTerminate(_ notification: Notification) {
        // Kill the Python server when app quits
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = ["-c", "lsof -ti:\(mainPort) | xargs kill -9 2>/dev/null"]
        try? process.run()
        process.waitUntilExit()
        thumbServer?.stop()
    }
}


// ============================================================
// On-demand Thumbnail Server
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
        let cacheKey = localIdentifier.replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: ":", with: "_")
        let cachePath = thumbDir + "/" + cacheKey + ".jpg"

        if FileManager.default.fileExists(atPath: cachePath) {
            return try? Data(contentsOf: URL(fileURLWithPath: cachePath))
        }

        let fetchResult = PHAsset.fetchAssets(withLocalIdentifiers: [localIdentifier], options: nil)
        guard let asset = fetchResult.firstObject else { return nil }

        let options = PHImageRequestOptions()
        options.isSynchronous = true
        options.deliveryMode = .fastFormat
        options.resizeMode = .fast
        options.isNetworkAccessAllowed = true

        var resultData: Data?
        let targetSize = CGSize(width: 400, height: 400)

        PHImageManager.default().requestImage(
            for: asset, targetSize: targetSize,
            contentMode: .aspectFill, options: options
        ) { image, _ in
            if let image = image {
                guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return }
                let rep = NSBitmapImageRep(cgImage: cgImage)
                if let jpeg = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.75]) {
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
