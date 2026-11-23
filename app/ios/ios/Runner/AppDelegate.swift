import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    GeneratedPluginRegistrant.register(with: self)
    if let controller = window?.rootViewController as? FlutterViewController {
      let channel = FlutterMethodChannel(
        name: "com.ethan.agent/share",
        binaryMessenger: controller.binaryMessenger
      )
      channel.setMethodCallHandler { [weak self] call, result in
        guard let args = call.arguments as? [String: Any],
              let typedData = args["bytes"] as? FlutterStandardTypedData,
              let image = UIImage(data: typedData.data) else {
          result(FlutterError(code: "INVALID_ARGS", message: "Invalid image data", details: nil))
          return
        }
        switch call.method {
        case "shareImage":
          let activityVC = UIActivityViewController(activityItems: [image], applicationActivities: nil)
          if let popover = activityVC.popoverPresentationController {
            popover.sourceView = controller.view
            popover.sourceRect = CGRect(
              x: controller.view.bounds.midX,
              y: controller.view.bounds.midY,
              width: 0,
              height: 0
            )
            popover.permittedArrowDirections = []
          }
          controller.present(activityVC, animated: true) {
            result(true)
          }
        case "saveImageToPhotos":
          UIImageWriteToSavedPhotosAlbum(image, self, #selector(self?.image(_:didFinishSavingWithError:contextInfo:)), nil)
          result(true)
        default:
          result(FlutterMethodNotImplemented)
        }
      }
    }
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  @objc private func image(
    _ image: UIImage,
    didFinishSavingWithError error: Error?,
    contextInfo: UnsafeRawPointer
  ) {
    // Saved callback
  }
}
