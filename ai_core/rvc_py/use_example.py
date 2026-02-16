
    
    from ai_core.rvc_py.rvc_infer import rvc_infer
    if args.rvc_model:
        print(f"[INFO] Post-process через RVC: {args.rvc_model}")
        rvc_kwargs = dict(device=args.device)
        if args.rvc_index:
            rvc_kwargs['index_path'] = args.rvc_index
        if args.rvc_index_rate:
            rvc_kwargs['index_rate'] = args.rvc_index_rate
        # Ensure waveform is 1D float32 numpy array for RVC/ RMVPE
        if isinstance(wav, torch.Tensor):
            wav = wav.detach().cpu().numpy()
        wav = np.asarray(wav)
        if wav.ndim > 1:
            wav = np.squeeze(wav)
        if wav.ndim != 1:
            wav = wav.reshape(-1)
        wav = wav.astype(np.float32, copy=False)
        wav, sr = rvc_infer(wav, sr, args.rvc_model, **rvc_kwargs)
    # Сохраняем результат
    print(f"[INFO] Saved output to {args.out}")
    wavfile.write(args.out, sr, wav.T if wav.ndim > 1 else wav)