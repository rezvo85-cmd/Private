Pod::Spec.new do |s|
  s.name           = 'RonnWakeWord'
  s.version        = '1.0.0'
  s.summary        = 'RONN offline iOS wake-word listener'
  s.description    = 'On-device keyword spotting bridge used by RONN Always Ready.'
  s.license        = { :type => 'MIT' }
  s.author         = 'RONN'
  s.homepage       = 'https://github.com/rezvo85-cmd/Private'
  s.platforms      = { :ios => '16.4' }
  s.source         = { :git => 'https://github.com/rezvo85-cmd/Private.git' }
  s.static_framework = true
  s.swift_version  = '6.0'

  s.dependency 'ExpoModulesCore'
  s.source_files = 'ios/**/*.{h,m,mm,swift}'
  s.exclude_files = 'ios/Vendor/**/*'
  s.resources = 'ios/Resources/**/*'
  s.vendored_frameworks = [
    'ios/Vendor/SherpaOnnx/sherpa-onnx.xcframework',
    'ios/Vendor/OnnxRuntime/onnxruntime.xcframework'
  ]

  s.frameworks = 'AVFoundation', 'CoreFoundation', 'Foundation', 'CoreML', 'Network'
  s.libraries = 'c++'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }
end
