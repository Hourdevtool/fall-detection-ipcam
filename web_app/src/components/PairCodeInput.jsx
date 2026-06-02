import { useState, useRef, useEffect } from 'react';
import './PairCodeInput.css';

export default function PairCodeInput({ length = 6, onComplete }) {
  const [values, setValues] = useState(Array(length).fill(''));
  const inputRefs = useRef([]);

  useEffect(() => {
    // Auto-focus first input
    if (inputRefs.current[0]) {
      inputRefs.current[0].focus();
    }
  }, []);

  function handleChange(index, e) {
    const val = e.target.value.replace(/\D/g, ''); // digits only
    if (!val) return;

    const newValues = [...values];
    newValues[index] = val[val.length - 1]; // take last digit
    setValues(newValues);

    // Move to next input
    if (index < length - 1) {
      inputRefs.current[index + 1]?.focus();
    }

    // Check if complete
    const fullCode = newValues.join('');
    if (fullCode.length === length && !newValues.includes('')) {
      onComplete?.(fullCode);
    }
  }

  function handleKeyDown(index, e) {
    if (e.key === 'Backspace') {
      const newValues = [...values];
      if (values[index]) {
        newValues[index] = '';
        setValues(newValues);
      } else if (index > 0) {
        newValues[index - 1] = '';
        setValues(newValues);
        inputRefs.current[index - 1]?.focus();
      }
    }
  }

  function handlePaste(e) {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, length);
    if (pasted) {
      const newValues = Array(length).fill('');
      for (let i = 0; i < pasted.length; i++) {
        newValues[i] = pasted[i];
      }
      setValues(newValues);
      
      const nextIndex = Math.min(pasted.length, length - 1);
      inputRefs.current[nextIndex]?.focus();
      
      if (pasted.length === length) {
        onComplete?.(pasted);
      }
    }
  }

  return (
    <div className="pair-code-input">
      {values.map((val, i) => (
        <input
          key={i}
          ref={(el) => (inputRefs.current[i] = el)}
          type="tel"
          inputMode="numeric"
          maxLength={1}
          value={val}
          onChange={(e) => handleChange(i, e)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onPaste={handlePaste}
          className={`pair-code-digit ${val ? 'filled' : ''}`}
          autoComplete="off"
        />
      ))}
    </div>
  );
}
